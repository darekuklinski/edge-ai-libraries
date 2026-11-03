# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

import asyncio
from unittest.mock import AsyncMock, Mock

from app.retrieval import retrieve_context


def test_retrieve_context_uses_default_retriever_without_attachments():
    expected_documents = [object()]
    default_retriever = Mock()
    default_retriever.ainvoke = AsyncMock(return_value=expected_documents)
    vectorstore = Mock()

    documents = asyncio.run(
        retrieve_context("question", [], vectorstore, default_retriever, 1, 3)
    )

    assert documents == expected_documents
    default_retriever.ainvoke.assert_awaited_once_with("question")
    vectorstore.as_retriever.assert_not_called()


def test_retrieve_context_scopes_one_attachment():
    expected_documents = [object()]
    scoped_retriever = Mock()
    scoped_retriever.ainvoke = AsyncMock(return_value=expected_documents)
    vectorstore = Mock()
    vectorstore.as_retriever.return_value = scoped_retriever
    default_retriever = Mock()
    attachments = [{"file_name": "report.pdf", "bucket_name": "default"}]

    documents = asyncio.run(
        retrieve_context(
            "question", attachments, vectorstore, default_retriever, 2, 6
        )
    )

    assert documents == expected_documents
    vectorstore.as_retriever.assert_called_once_with(
        search_type="mmr",
        search_kwargs={
            "k": 2,
            "fetch_k": 6,
            "filter": {
                "$and": [
                    {"bucket": {"$eq": "default"}},
                    {"filename": {"$eq": "report.pdf"}},
                ]
            },
        },
    )
    scoped_retriever.ainvoke.assert_awaited_once_with("question")
    default_retriever.ainvoke.assert_not_called()


def test_retrieve_context_scopes_multiple_attachments():
    scoped_retriever = Mock()
    scoped_retriever.ainvoke = AsyncMock(return_value=[])
    vectorstore = Mock()
    vectorstore.as_retriever.return_value = scoped_retriever
    attachments = [
        {"file_name": "report.pdf", "bucket_name": "default"},
        {"file_name": "notes.txt", "bucket_name": "research"},
    ]

    asyncio.run(
        retrieve_context("question", attachments, vectorstore, Mock(), 1, 3)
    )

    assert vectorstore.as_retriever.call_args.kwargs["search_kwargs"]["filter"] == {
        "$or": [
            {
                "$and": [
                    {"bucket": {"$eq": "default"}},
                    {"filename": {"$eq": "report.pdf"}},
                ]
            },
            {
                "$and": [
                    {"bucket": {"$eq": "research"}},
                    {"filename": {"$eq": "notes.txt"}},
                ]
            },
        ]
    }
