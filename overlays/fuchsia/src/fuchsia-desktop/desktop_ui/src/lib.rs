// Copyright 2026 The Fuchsia Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

//! Shared Instrument Studio desktop UI primitives.
//!
//! This crate is intentionally toolkit-light: tokens, chrome regions, and
//! layout contracts first. Carnelian adapters can consume these values without
//! forcing every app onto one widget runtime on day one.

pub mod chrome;
pub mod tokens;

pub use chrome::{ChromeRegion, InstrumentStudioLayout, WorkspaceId};
pub use tokens::{ColorRgba, ThemeTokens, INSTRUMENT_STUDIO_THEME};
