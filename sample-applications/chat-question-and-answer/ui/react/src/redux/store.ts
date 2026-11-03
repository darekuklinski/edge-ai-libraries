// Copyright (C) 2024 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

import { combineReducers, configureStore } from "@reduxjs/toolkit";
import conversationReducer from "./Conversation/ConversationSlice";
import { TypedUseSelectorHook, useDispatch, useSelector } from "react-redux";

export const store = configureStore({
  reducer: combineReducers({
    conversationReducer,
  }),
  devTools: import.meta.env.PROD || true,
  preloadedState: loadFromLocalStorage(),
  middleware: (getDefaultMiddleware) =>
    getDefaultMiddleware({
      serializableCheck: false,
    }),
});

function saveToLocalStorage(state: ReturnType<typeof store.getState>) {
  try {
    const serialState = JSON.stringify({
      ...state,
      conversationReducer: {
        ...state.conversationReducer,
        conversations: [],
        selectedConversationId: "",
        onGoingResults: {},
        isGenerating: {},
        isWaitingForFirstToken: {},
      },
    });
    localStorage.setItem("reduxStore", serialState);
  } catch (e) {
    console.warn(e);
  }
}

function loadFromLocalStorage() {
  try {
    const serialisedState = localStorage.getItem("reduxStore");
    if (serialisedState === null) return undefined;
    const state = JSON.parse(serialisedState);
    if (state?.conversationReducer) {
      state.conversationReducer.conversations = [];
      state.conversationReducer.selectedConversationId = "";
      state.conversationReducer.onGoingResults = {};
      state.conversationReducer.isGenerating = {};
      state.conversationReducer.isWaitingForFirstToken = {};
      localStorage.setItem("reduxStore", JSON.stringify(state));
    }
    return state;
  } catch (e) {
    console.warn(e);
    return undefined;
  }
}

store.subscribe(() => saveToLocalStorage(store.getState()));
console.log(store);
export default store;
export type AppDispatch = typeof store.dispatch;
export type RootState = ReturnType<typeof store.getState>;

export const useAppDispatch: () => AppDispatch = useDispatch;
export const useAppSelector: TypedUseSelectorHook<RootState> = useSelector;
