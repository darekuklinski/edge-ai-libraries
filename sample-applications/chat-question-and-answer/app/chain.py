# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

import os
from sqlalchemy.ext.asyncio import create_async_engine
from langchain_core.callbacks.streaming_stdout import StreamingStdOutCallbackHandler
from langchain_postgres.vectorstores import PGVector as EGAIVectorDB
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import (
    RunnableParallel,
    RunnablePassthrough,
    RunnableLambda,
)
from langchain_core.vectorstores import VectorStoreRetriever as EGAIVectorStoreRetriever
from langchain_openai import ChatOpenAI as EGAIModelServing
from langchain_openai import OpenAIEmbeddings as EGAIEmbeddings
from .custom_reranker import CustomReranker
from .retrieval import retrieve_context
import logging
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
import openlit

logging.basicConfig(level=logging.INFO)

# Check if OTLP endpoint is set in environment variables
otlp_endpoint = os.environ.get("OTLP_ENDPOINT", False)

# Initialize OpenTelemetry
if not isinstance(trace.get_tracer_provider(), TracerProvider):
    tracer_provider = TracerProvider()
    trace.set_tracer_provider(tracer_provider)

    # Set up OTLP exporter and span processor
    if not otlp_endpoint:
        logging.warning(
            "No OTLP endpoint provided - Telemetry data will not be collected."
        )
    else:
        otlp_exporter = OTLPSpanExporter()
        span_processor = BatchSpanProcessor(otlp_exporter)
        tracer_provider.add_span_processor(span_processor)

        openlit.init(
            otlp_endpoint=otlp_endpoint,
            application_name=os.environ.get("OTEL_SERVICE_NAME", "chatqna"),
            environment=os.environ.get("OTEL_SERVICE_ENV", "chatqna"),
        )

        logging.info(
            f"Tracing enabled: OpenTelemetry configured using OTLP endpoint at {otlp_endpoint}"
        )

PG_CONNECTION_STRING = os.getenv("PG_CONNECTION_STRING")
MODEL_NAME = os.getenv("EMBEDDING_MODEL", "Alibaba-NLP/gte-large-en-v1.5")
EMBEDDING_ENDPOINT_URL = os.getenv("EMBEDDING_ENDPOINT_URL", "http://localhost:6006")
COLLECTION_NAME = os.getenv("INDEX_NAME")
FETCH_K = int(os.getenv("FETCH_K", "1"))

engine = create_async_engine(PG_CONNECTION_STRING)

# Init Embeddings via Intel Edge GenerativeAI Suite
try:
    embedder = EGAIEmbeddings(
        openai_api_key="EMPTY",
        openai_api_base="{}".format(EMBEDDING_ENDPOINT_URL),
        model=MODEL_NAME
    )
    logging.info(
        f"Embeddings initialized with endpoint configured in EMBEDDING_ENDPOINT_URL"
    )
except Exception as e:
    logging.error(f"Failed to initialize embeddings: {str(e)}")
    raise

knowledge_base = EGAIVectorDB(
    embeddings=embedder,
    collection_name=COLLECTION_NAME,
    connection=engine,
)
retriever = EGAIVectorStoreRetriever(
    vectorstore=knowledge_base,
    search_type="mmr",
    search_kwargs={"k": FETCH_K, "fetch_k": FETCH_K * 3},
)

# Define our prompt
template = """
<|start|>system<|message|>
Reasoning: none
SYSTEM CONSTRAINT: 
You have no access to the internet.
Don't hesitate to ask questions when in doubt, especially when question is unclear.
If You don't know the answer just say it.
IMPORTANT: For longer answers use markdown as below. If answear is short, you can use regular text.:

**Example:**
## Topic Title 
Here's regular text with
**important points** and *emphasized terms.*
### Key Benefits:
- **Benefit 1:** Clear description
- **Benefit 2:** Another point
> 💡 **Pro Tip:** This makes information stand out!
### Sample Table:
| Syntax      | Description | Notes |
| :---------- | :---------: | ----: |
| Header      | Title       | Note1 |
| Paragraph   | Text        | Note2 |
### Sample Code:
```python
def example_function():
    print("This is a code block")
```
Always prioritize clarity and scannability in your responses.
<|end|><|start|>user<|message|>
Conversation history: {history}
Retrieved context:
{context}

Use retrieved context when relevant and combine it with your general knowledge. If the context does not contain the answer, be clear about that and answer from your general knowledge when possible. Do not invent facts or claim that unsupported statements came from the context.
prompt: {question}
<|end|><|start|>assistant
"""


prompt = ChatPromptTemplate.from_template(template)

ENDPOINT_URL = os.getenv("ENDPOINT_URL", "http://localhost:8080")

# Check which LLM inference backend is being used
LLM_BACKEND = None
if "ovms" in ENDPOINT_URL.lower():
    LLM_BACKEND = "ovms"
elif "text-generation" in ENDPOINT_URL.lower():
    LLM_BACKEND = "text-generation"
elif "vllm" in ENDPOINT_URL.lower():
    LLM_BACKEND = "vllm"
else:
    LLM_BACKEND = "unknown"

logging.info(f"Using LLM inference backend: {LLM_BACKEND}")
LLM_MODEL = os.getenv("LLM_MODEL", "Intel/neural-chat-7b-v3-3")
RERANKER_ENDPOINT = os.getenv("RERANKER_ENDPOINT", "http://localhost:9090/rerank")
callbacks = [StreamingStdOutCallbackHandler()]

async def context_retriever_fn(chain_inputs: dict):
    """
    Retrieve relevant documents for a given question and conversation history.

    Args:
        chain_inputs (dict): Dictionary with "question" and "history" keys.

    Returns:
        list: List of relevant Document objects (may be empty if no question or no results).

    Raises:
        ValueError: If chain_inputs is not a dict.
    """
    if not isinstance(chain_inputs, dict):
        raise ValueError("Invalid input: chain_inputs must be a dictionary.")

    # in process chunks we already raise value error for empty question, but to keep shape consistent we return empty list here
    question = chain_inputs.get("question", "")
    if not question:
        return {}  # to keep shape consistent

    attachments = chain_inputs.get("attachments", [])
    return await retrieve_context(
        question,
        attachments,
        knowledge_base,
        retriever,
        FETCH_K,
        FETCH_K * 3,
    )

# Format the context in a readable way
def format_docs(docs):
    """
    Format a list of Document objects into a readable string for prompt context.

    Args:
        docs (list): List of Document objects (each with .page_content and .metadata attributes).

    Returns:
        str: Formatted string with each document's sl.no , content and source, or a message if no docs are found.
    """
    if not docs:
        return "No relevant context found."
    
    formatted_docs = []
    for i, doc in enumerate(docs, 1):
        content = doc.page_content.strip()
        metadata = doc.metadata or {}
        source = metadata.get("source", "Unknown source")
        
        formatted_docs.append(f"[Document {i}] {content}\nSource: {source}")
    
    return "\n\n".join(formatted_docs)

async def process_chunks(conversation_messages, max_tokens, attachments=None):
    """
    Process a list of conversation messages and stream the LLM-generated answer.

    This function builds the retrieval-augmented generation (RAG) chain, including context retrieval,
    reranking, prompt formatting, and LLM inference. It streams the output as server-sent events.

    Args:
        conversation_messages (list): List of message objects, each with 'role' and 'content'.
        The last message is treated as the user's question.

        max_tokens (int): Maximum number of tokens for the LLM response (if supported by backend).

    Yields:
        str: Server-sent event strings ("data: ...\n\n") with the LLM's output chunks.

    Raises:
        ValueError: If the question text is empty or only whitespace.
    """
    # All messages except the last one are considered history as last message is question
    if len(conversation_messages) > 1:
        valid_history_msgs = []
        for msg in conversation_messages[:-1]:
            # Check for malformed messages without 'role' or 'content' and ensure content is not None
            if hasattr(msg, "role") and hasattr(msg, "content") and msg.content is not None:
                valid_history_msgs.append(f"{msg.role}: {msg.content}")
            else:
                logging.warning("Skipping history message: missing 'role' or 'content'")
        history = "\n".join(valid_history_msgs)
    else:
        # In case there is 1 or no message object, history will be considered empty
        history = ""

    # Raise valueError if question is empty or only whitespace
    question_text = conversation_messages[-1].content
    if not question_text or not question_text.strip():
        raise ValueError("Question text cannot be empty")

    context_retriever = RunnableLambda(context_retriever_fn) # it passes all chain_input dict to context_retriever fn

    if LLM_BACKEND in ["vllm", "unknown"]:
        seed_value = None
        model = EGAIModelServing(
            openai_api_key="EMPTY",
            openai_api_base="{}".format(ENDPOINT_URL),
            model_name=LLM_MODEL,
            top_p=0.99,
            temperature=0.01,
            streaming=True,
            callbacks=callbacks,
            stop=["\n\n"],
        )
    else:
        seed_value = int(os.getenv("SEED", 42))
        model = EGAIModelServing(
            openai_api_key="EMPTY",
            openai_api_base="{}".format(ENDPOINT_URL),
            model_name=LLM_MODEL,
            top_p=0.99,
            temperature=0.01,
            streaming=True,
            callbacks=callbacks,
            seed=seed_value,
            max_tokens=max_tokens
        )

    re_ranker = CustomReranker(reranking_endpoint=RERANKER_ENDPOINT)
    re_ranker_lambda = RunnableLambda(re_ranker.rerank)

    # RAG Chain
    chain = (
        RunnableParallel({
            "context": context_retriever,  # context retrieved from vector store
            "question": lambda x: x["question"],  # passes through the question
            "history": lambda x: x["history"]  # passes through the history
        })
        | re_ranker_lambda
        | {"context": (lambda x: format_docs(x["context"])), "question": lambda x: x["question"], "history": lambda x: x["history"]}
        | prompt
        | model
        | StrOutputParser()
    )

    # Run the chain with all inputs
    chain_input = {
        "history": history, # chain will call context_retriever internally, no need to add it.
        "question": question_text,
        "attachments": attachments or [],
    }

    async for log in chain.astream(chain_input):
        if log == "\n":
            yield f"data: \\n\\n\n\n"
        elif log.endswith("\n"):
            yield f"data: {log}\n\n"
            yield f"data: \\n\\n\n\n"
        else:
            yield f"data: {log}\n\n"
        #yield f"data: {log}\n\n"
