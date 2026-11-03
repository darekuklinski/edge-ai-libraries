# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

from typing import Any, Mapping, Sequence


def _attachment_filter(attachments: Sequence[Mapping[str, str]]) -> dict[str, Any]:
    file_filters = [
        {
            "$and": [
                {"bucket": {"$eq": attachment["bucket_name"]}},
                {"filename": {"$eq": attachment["file_name"]}},
            ]
        }
        for attachment in attachments
    ]
    return file_filters[0] if len(file_filters) == 1 else {"$or": file_filters}


async def retrieve_context(
    question: str,
    attachments: Sequence[Mapping[str, str]],
    vectorstore: Any,
    default_retriever: Any,
    k: int,
    fetch_k: int,
) -> list[Any]:
    if not attachments:
        return await default_retriever.ainvoke(question)

    scoped_retriever = vectorstore.as_retriever(
        search_type="mmr",
        search_kwargs={
            "k": k,
            "fetch_k": fetch_k,
            "filter": _attachment_filter(attachments),
        },
    )
    return await scoped_retriever.ainvoke(question)
