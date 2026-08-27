// Copyright 2026 The Fuchsia Desktop Authors.
// Use of this source code is governed by a BSD-style license.

use anyhow::{Context, Result};
use fidl_fuchsia_ui_test_input::{
    KeyboardMarker, KeyboardSimulateUsAsciiTextEntryRequest, RegistryMarker,
    RegistryRegisterKeyboardRequest,
};
use fuchsia_component::client::connect_to_protocol;

#[fuchsia::main]
async fn main() -> Result<()> {
    let registry = connect_to_protocol::<RegistryMarker>().context("connect input registry")?;
    let (keyboard, keyboard_server) = fidl::endpoints::create_proxy::<KeyboardMarker>();
    registry
        .register_keyboard(RegistryRegisterKeyboardRequest {
            device: Some(keyboard_server),
            ..Default::default()
        })
        .await
        .context("register synthetic keyboard")?;
    keyboard
        .simulate_us_ascii_text_entry(&KeyboardSimulateUsAsciiTextEntryRequest {
            text: Some("fuchsia-studio help\n".to_string()),
            ..Default::default()
        })
        .await
        .context("type bounded Terminal proof command")?;
    Ok(())
}
