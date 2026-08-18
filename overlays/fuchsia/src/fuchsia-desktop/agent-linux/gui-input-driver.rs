// Copyright 2026 The Fuchsia Desktop Authors.
// Use of this source code is governed by a BSD-style license.

use anyhow::{Context as _, Result};
use fidl_fuchsia_input as finput;
use fidl_fuchsia_math as fmath;
use fidl_fuchsia_ui_test_input::{
    CoordinateUnit, KeyboardMarker, KeyboardSimulateKeyPressRequest, RegistryMarker,
    RegistryRegisterKeyboardRequest, RegistryRegisterTouchScreenRequest, TouchScreenMarker,
    TouchScreenSimulateTapRequest,
};
use fuchsia_component::client::connect_to_protocol;

#[fuchsia::main(logging = true)]
async fn main() -> Result<()> {
    let registry = connect_to_protocol::<RegistryMarker>().context("connect input registry")?;

    let (touch, touch_server) = fidl::endpoints::create_proxy::<TouchScreenMarker>();
    registry
        .register_touch_screen(RegistryRegisterTouchScreenRequest {
            device: Some(touch_server),
            coordinate_unit: Some(CoordinateUnit::PhysicalPixels),
            ..Default::default()
        })
        .await
        .context("register synthetic touchscreen")?;
    touch
        .simulate_tap(&TouchScreenSimulateTapRequest {
            tap_location: Some(fmath::Vec_ { x: 360, y: 600 }),
            ..Default::default()
        })
        .await
        .context("focus Linux framebuffer view")?;
    fuchsia_async::Timer::new(zx::MonotonicDuration::from_millis(250)).await;

    let (keyboard, keyboard_server) = fidl::endpoints::create_proxy::<KeyboardMarker>();
    registry
        .register_keyboard(RegistryRegisterKeyboardRequest {
            device: Some(keyboard_server),
            ..Default::default()
        })
        .await
        .context("register synthetic keyboard")?;
    keyboard
        .simulate_key_press(&KeyboardSimulateKeyPressRequest {
            key_code: Some(finput::Key::K),
            ..Default::default()
        })
        .await
        .context("inject bounded Linux GUI physical key")?;
    log::info!("Injected bounded Linux GUI focus and keyboard journey");
    Ok(())
}
