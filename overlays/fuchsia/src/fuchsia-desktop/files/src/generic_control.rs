// Copyright 2026 The Fuchsia Desktop Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

use anyhow::{ensure, Context as _, Result};
use std::path::Path;

#[fuchsia::main(logging = true)]
async fn main() -> Result<()> {
    let files_seed = Path::new("/data/Welcome.txt");
    ensure!(!files_seed.exists(), "generic element can see Files component storage");
    std::fs::write("/data/generic-control.txt", "isolated")
        .context("write generic element storage marker")?;
    ensure!(!files_seed.exists(), "Files marker appeared after generic write");
    log::info!("Generic element storage is isolated from Fuchsia Files");
    Ok(())
}
