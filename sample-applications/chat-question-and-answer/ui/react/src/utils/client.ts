// Copyright (C) 2024 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

import axios from "axios";

//add iterceptors to add any request headers

axios.defaults.withCredentials = true;

export default axios;
