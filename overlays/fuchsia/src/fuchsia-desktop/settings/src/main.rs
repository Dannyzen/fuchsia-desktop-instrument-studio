// Copyright 2026 The Fuchsia Desktop Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

use anyhow::{anyhow, Context as _, Error};
use fidl::endpoints::create_proxy;
use fidl_fuchsia_buildinfo::ProviderMarker as BuildInfoMarker;
use fidl_fuchsia_hwinfo::ProductMarker;
use fidl_fuchsia_intl::TemperatureUnit as FidlTemperatureUnit;
use fidl_fuchsia_math as fmath;
use fidl_fuchsia_settings::{IntlMarker, IntlProxy, IntlSettings};
use fidl_fuchsia_ui_app::{ViewProviderRequest, ViewProviderRequestStream};
use fidl_fuchsia_ui_composition as flatland;
use fidl_fuchsia_ui_pointer as pointer;
use fidl_fuchsia_ui_views as views;
use fuchsia_async as fasync;
use fuchsia_component::{client::connect_to_protocol, server::ServiceFs};
use futures::channel::mpsc::{unbounded, UnboundedSender};
use futures::{StreamExt as _, TryStreamExt as _};
use log::{info, warn};

mod settings_core;
mod settings_ui;
mod text_surface;

use settings_core::{AppTheme, SettingsController, SettingsOwners, TemperatureUnit};
use settings_ui::{action_for_point, UiAction};
use text_surface::{TextStyle, TextSurface};

const BACKGROUND: flatland::ColorRgba =
    flatland::ColorRgba { red: 0.035, green: 0.039, blue: 0.047, alpha: 1.0 };
const PANEL: flatland::ColorRgba =
    flatland::ColorRgba { red: 0.102, green: 0.110, blue: 0.129, alpha: 1.0 };
const SURFACE: flatland::ColorRgba =
    flatland::ColorRgba { red: 0.176, green: 0.188, blue: 0.216, alpha: 1.0 };
const SELECTED: flatland::ColorRgba =
    flatland::ColorRgba { red: 0.060, green: 0.280, blue: 0.340, alpha: 1.0 };
const ACCENT: flatland::ColorRgba =
    flatland::ColorRgba { red: 0.357, green: 0.784, blue: 0.839, alpha: 1.0 };
const CONTRAST: flatland::ColorRgba =
    flatland::ColorRgba { red: 0.350, green: 0.180, blue: 0.030, alpha: 1.0 };
const ERROR: flatland::ColorRgba =
    flatland::ColorRgba { red: 0.450, green: 0.080, blue: 0.040, alpha: 1.0 };

fn create_rect(
    flatland: &flatland::FlatlandProxy,
    parent: &flatland::TransformId,
    transform_value: u64,
    content_value: u64,
    color: &flatland::ColorRgba,
    size: fmath::SizeU,
    translation: fmath::Vec_,
) -> Result<(), Error> {
    let transform = flatland::TransformId { value: transform_value };
    let content = flatland::ContentId { value: content_value };
    flatland.create_transform(&transform)?;
    flatland.create_filled_rect(&content)?;
    flatland.set_solid_fill(&content, color, &size)?;
    flatland.set_content(&transform, &content)?;
    flatland.set_translation(&transform, &translation)?;
    flatland.add_child(parent, &transform)?;
    Ok(())
}

async fn watch_touch_source(
    touch_source: pointer::TouchSourceProxy,
    sender: UnboundedSender<[f32; 2]>,
) {
    let mut pending_responses = Vec::new();
    let mut pending_interactions: Vec<(pointer::TouchInteractionId, Option<[f32; 2]>)> = Vec::new();
    loop {
        let events = match touch_source.watch(&pending_responses).await {
            Ok(events) => events,
            Err(error) => {
                warn!("Settings TouchSource closed: {error:?}");
                return;
            }
        };
        pending_responses = events
            .iter()
            .map(|event| {
                if event.pointer_sample.is_some() {
                    pointer::TouchResponse {
                        response_type: Some(pointer::TouchResponseType::Yes),
                        ..Default::default()
                    }
                } else {
                    pointer::TouchResponse::default()
                }
            })
            .collect();
        for event in events {
            if let Some(sample) = event.pointer_sample {
                if let (Some(interaction), Some(pointer::EventPhase::Add), Some(position)) =
                    (sample.interaction, sample.phase, sample.position_in_viewport)
                {
                    if let Some((_, stored)) = pending_interactions
                        .iter_mut()
                        .find(|(stored_interaction, _)| *stored_interaction == interaction)
                    {
                        *stored = Some(position);
                    } else {
                        pending_interactions.push((interaction, Some(position)));
                    }
                }
            }
            if let Some(result) = event.interaction_result {
                if let Some(index) = pending_interactions
                    .iter()
                    .position(|(interaction, _)| *interaction == result.interaction)
                {
                    let (_, position) = pending_interactions.swap_remove(index);
                    if result.status == pointer::TouchInteractionStatus::Granted {
                        if let Some(position) = position {
                            if sender.unbounded_send(position).is_err() {
                                return;
                            }
                        }
                    }
                }
            }
        }
    }
}

fn from_fidl_temperature(unit: FidlTemperatureUnit) -> TemperatureUnit {
    match unit {
        FidlTemperatureUnit::Fahrenheit => TemperatureUnit::Fahrenheit,
        FidlTemperatureUnit::Celsius => TemperatureUnit::Celsius,
    }
}

fn to_fidl_temperature(unit: TemperatureUnit) -> FidlTemperatureUnit {
    match unit {
        TemperatureUnit::Celsius => FidlTemperatureUnit::Celsius,
        TemperatureUnit::Fahrenheit => FidlTemperatureUnit::Fahrenheit,
    }
}

async fn load_system_info() -> (String, String, bool, bool) {
    let mut build_line = "Build information unavailable".to_string();
    let mut product_line = "Product information unavailable".to_string();
    let mut build_available = false;
    let mut product_available = false;
    if let Ok(proxy) = connect_to_protocol::<BuildInfoMarker>() {
        if let Ok(info) = proxy.get_build_info().await {
            build_line = format!(
                "Build: {} / {}",
                info.product_config.as_deref().unwrap_or("unknown product"),
                info.version.as_deref().unwrap_or("unknown version")
            );
            build_available = true;
        }
    }
    if let Ok(proxy) = connect_to_protocol::<ProductMarker>() {
        if let Ok(info) = proxy.get_info().await {
            product_line = format!(
                "Product: {} / {}",
                info.name.as_deref().unwrap_or("Fuchsia device"),
                info.model.as_deref().unwrap_or("unknown model")
            );
            product_available = true;
        }
    }
    (build_line, product_line, build_available, product_available)
}

async fn load_intl() -> (Option<IntlProxy>, TemperatureUnit) {
    let Ok(proxy) = connect_to_protocol::<IntlMarker>() else {
        return (None, TemperatureUnit::Celsius);
    };
    match proxy.watch().await {
        Ok(settings) => {
            let unit = settings
                .temperature_unit
                .map(from_fidl_temperature)
                .unwrap_or(TemperatureUnit::Celsius);
            (Some(proxy), unit)
        }
        Err(error) => {
            warn!("Intl watch unavailable: {error:?}");
            (None, TemperatureUnit::Celsius)
        }
    }
}

async fn apply_temperature(proxy: &IntlProxy, unit: TemperatureUnit) -> Result<(), String> {
    let settings = IntlSettings {
        temperature_unit: Some(to_fidl_temperature(unit)),
        ..Default::default()
    };
    match proxy.set(&settings).await {
        Ok(Ok(())) => Ok(()),
        Ok(Err(error)) => Err(format!("Intl rejected setting: {error:?}")),
        Err(error) => Err(format!("Intl transport failed: {error:?}")),
    }
}

struct DynamicSurfaces {
    theme_value: TextSurface,
    temperature_value: Option<TextSurface>,
    status: TextSurface,
}

#[derive(Clone, Copy)]
struct LayoutMetrics {
    btn_w: u32,
    btn_h: u32,
    status_w: u32,
    status_h: u32,
}

async fn refresh_ui(
    flatland: &flatland::FlatlandProxy,
    controller: &SettingsController,
    surfaces: &mut DynamicSurfaces,
    metrics: LayoutMetrics,
) -> Result<(), Error> {
    surfaces
        .theme_value
        .update(flatland, &format!("Current: {}", controller.theme().label()))
        .await?;
    if let Some(surface) = surfaces.temperature_value.as_mut() {
        surface
            .update(flatland, &format!("Current: {}", controller.temperature().label()))
            .await?;
    }
    surfaces.status.update(flatland, controller.status()).await?;
    let btn = fmath::SizeU { width: metrics.btn_w, height: metrics.btn_h };
    flatland.set_solid_fill(
        &flatland::ContentId { value: 21 },
        if controller.theme() == AppTheme::Dark { &SELECTED } else { &SURFACE },
        &btn,
    )?;
    flatland.set_solid_fill(
        &flatland::ContentId { value: 23 },
        if controller.theme() == AppTheme::Contrast { &CONTRAST } else { &SURFACE },
        &btn,
    )?;
    flatland.set_solid_fill(
        &flatland::ContentId { value: 25 },
        if controller.temperature() == TemperatureUnit::Celsius { &SELECTED } else { &SURFACE },
        &btn,
    )?;
    flatland.set_solid_fill(
        &flatland::ContentId { value: 27 },
        if controller.temperature() == TemperatureUnit::Fahrenheit { &SELECTED } else { &SURFACE },
        &btn,
    )?;
    flatland.set_solid_fill(
        &flatland::ContentId { value: 41 },
        if controller.status().starts_with("Apply failed") { &ERROR } else { &PANEL },
        &fmath::SizeU { width: metrics.status_w, height: metrics.status_h },
    )?;
    flatland.present(flatland::PresentArgs::default())?;
    Ok(())
}

async fn create_settings_view(root_token: views::ViewCreationToken) -> Result<(), Error> {
    let flatland = connect_to_protocol::<flatland::FlatlandMarker>()
        .context("connect to Flatland")?;
    let (parent_watcher, parent_watcher_server) =
        create_proxy::<flatland::ParentViewportWatcherMarker>();
    let (touch_source, touch_source_server) = create_proxy::<pointer::TouchSourceMarker>();
    let view_ref_pair = fuchsia_scenic::ViewRefPair::new()?;
    flatland.r#create_view2(
        root_token,
        views::ViewIdentityOnCreation::from(view_ref_pair),
        flatland::ViewBoundProtocols { touch_source: Some(touch_source_server), ..Default::default() },
        parent_watcher_server,
    )?;
    let layout = parent_watcher.r#get_layout().await?;
    let size = layout.logical_size.ok_or_else(|| anyhow!("parent supplied no logical size"))?;
    let root = flatland::TransformId { value: 1 };
    flatland.create_transform(&root)?;
    flatland.set_root_transform(&root)?;
    flatland.set_hit_regions(
        &root,
        &[flatland::HitRegion {
            region: fmath::RectF { x: 0.0, y: 0.0, width: size.width as f32, height: size.height as f32 },
            hit_test: flatland::HitTestInteraction::Default,
        }],
    )?;
    create_rect(&flatland, &root, 2, 3, &BACKGROUND, size, fmath::Vec_ { x: 0, y: 0 })?;
    create_rect(
        &flatland,
        &root,
        4,
        5,
        &PANEL,
        fmath::SizeU { width: size.width, height: 88 },
        fmath::Vec_ { x: 0, y: 0 },
    )?;
    create_rect(
        &flatland,
        &root,
        6,
        7,
        &ACCENT,
        fmath::SizeU { width: 8, height: 88 },
        fmath::Vec_ { x: 0, y: 0 },
    )?;

    let (intl_proxy, current_temperature) = load_intl().await;
    let (build_line, product_line, build_available, product_available) = load_system_info().await;
    let owners = SettingsOwners {
        app_preferences: true,
        intl_service: intl_proxy.is_some(),
        build_info: build_available,
        product_info: product_available,
    };
    let mut controller = SettingsController::load("/data", owners, current_temperature)
        .map_err(|error| anyhow!(error))?;
    let injected_failure = std::env::args().any(|argument| argument == "--inject-intl-failure");
    if injected_failure {
        let target = if current_temperature == TemperatureUnit::Celsius {
            TemperatureUnit::Fahrenheit
        } else {
            TemperatureUnit::Celsius
        };
        let _ = controller.record_temperature_result(
            target,
            Err("injected Intl apply failure".to_string()),
        );
    }

    let narrow = size.width < 520 || (size.height > size.width && size.width < 800);
    let sidebar_w = if narrow { 56 } else { 140 };
    let card_x = sidebar_w + 8;
    let card_w = size.width.saturating_sub(card_x + 8).max(80);
    let btn_x = card_x + 12;
    let btn_w = if narrow { card_w.saturating_sub(24).max(80) } else { 240 };
    let btn_h = if narrow { 40 } else { 80 };
    let info_w = if narrow { card_w } else { 640 };
    let status_w = size.width.saturating_sub(16).max(80);
    let status_h = if narrow { 28 } else { 80 };
    let status_y = if narrow {
        size.height.saturating_sub(32).max(360) as i32
    } else {
        size.height.saturating_sub(96) as i32
    };
    let info_h = if narrow { 36 } else { 216 };
    let info_y = if narrow { 308 } else { 488 };
    let metrics = LayoutMetrics { btn_w, btn_h, status_w, status_h };
    let rects = if narrow {
        [
            (10, 11, &PANEL, sidebar_w, size.height, 0, 0),
            (12, 13, &SELECTED, sidebar_w.saturating_sub(8), 40, 4, 12),
            (14, 15, &PANEL, sidebar_w.saturating_sub(8), 40, 4, 60),
            (16, 17, &PANEL, sidebar_w.saturating_sub(8), 40, 4, 108),
            (18, 19, &PANEL, card_w, 148, card_x as i32, 8),
            (20, 21, &SURFACE, btn_w, btn_h, btn_x as i32, 44),
            (22, 23, &SURFACE, btn_w, btn_h, btn_x as i32, 92),
            (28, 29, &PANEL, card_w, 148, card_x as i32, 164),
            (24, 25, &SURFACE, btn_w, btn_h, btn_x as i32, 200),
            (26, 27, &SURFACE, btn_w, btn_h, btn_x as i32, 248),
            (30, 31, &PANEL, info_w, info_h, card_x as i32, info_y),
            (40, 41, &PANEL, status_w, status_h, 8, status_y),
        ]
    } else {
        [
            (10, 11, &PANEL, sidebar_w, size.height, 0, 0),
            (12, 13, &SELECTED, sidebar_w.saturating_sub(16), 44, 8, 16),
            (14, 15, &PANEL, sidebar_w.saturating_sub(16), 44, 8, 68),
            (16, 17, &PANEL, sidebar_w.saturating_sub(16), 44, 8, 120),
            (18, 19, &PANEL, 560, 200, 160, 16),
            (20, 21, &SURFACE, 240, 80, 176, 72),
            (22, 23, &SURFACE, 240, 80, 432, 72),
            (28, 29, &PANEL, 560, 200, 160, 232),
            (24, 25, &SURFACE, 240, 80, 176, 288),
            (26, 27, &SURFACE, 240, 80, 432, 288),
            (30, 31, &PANEL, 640, 216, 160, 448),
            (40, 41, &PANEL, 688, 80, 16, size.height.saturating_sub(96) as i32),
        ]
    };
    for (transform, content, color, width, height, x, y) in rects {
        create_rect(
            &flatland,
            &root,
            transform,
            content,
            color,
            fmath::SizeU { width, height },
            fmath::Vec_ { x, y },
        )?;
    }
    // Paint sidebar + cards before text so a TextSurface failure cannot leave a gray slab.
    flatland.present(flatland::PresentArgs::default())?;

    let mut static_text = Vec::new();
    let text_specs: Vec<(u64, u64, u32, u32, i32, i32, &str, TextStyle)> = if narrow {
        vec![
            (110, 111, card_w.saturating_sub(16), 20, (card_x + 12) as i32, 14, "Appearance", TextStyle { font_size: 13.0, left_padding: 2, top_padding: 2 }),
            (112, 113, btn_w, btn_h, btn_x as i32, 44, "Dark", TextStyle { font_size: 14.0, left_padding: 10, top_padding: 10 }),
            (116, 117, btn_w, btn_h, btn_x as i32, 92, "Contrast", TextStyle { font_size: 14.0, left_padding: 10, top_padding: 10 }),
            (120, 121, card_w.saturating_sub(16), 20, (card_x + 12) as i32, 170, "Temperature", TextStyle { font_size: 13.0, left_padding: 2, top_padding: 2 }),
            (124, 125, btn_w, btn_h, btn_x as i32, 200, "Celsius", TextStyle { font_size: 14.0, left_padding: 10, top_padding: 10 }),
            (128, 129, btn_w, btn_h, btn_x as i32, 248, "Fahrenheit", TextStyle { font_size: 14.0, left_padding: 10, top_padding: 10 }),
            (132, 133, card_w.saturating_sub(8), 20, (card_x + 8) as i32, info_y + 2, "System", TextStyle { font_size: 12.0, left_padding: 2, top_padding: 2 }),
            (136, 137, info_w.saturating_sub(12), 16, (card_x + 8) as i32, info_y + 18, &build_line, TextStyle { font_size: 10.0, left_padding: 2, top_padding: 1 }),
            (140, 141, 1, 1, -64, -64, &product_line, TextStyle { font_size: 10.0, left_padding: 2, top_padding: 1 }),
            (144, 145, 1, 1, -64, -64, "build-info + hwinfo", TextStyle { font_size: 10.0, left_padding: 2, top_padding: 1 }),
        ]
    } else {
        vec![
            (100, 101, 300, 56, 24, 16, "Fuchsia Settings", TextStyle { font_size: 25.0, left_padding: 8, top_padding: 7 }),
            (104, 105, 360, 48, 344, 20, "Backed controls only", TextStyle { font_size: 17.0, left_padding: 8, top_padding: 9 }),
            (108, 109, 300, 44, 48, 120, "Appearance", TextStyle { font_size: 21.0, left_padding: 8, top_padding: 5 }),
            (112, 113, 240, 80, 80, 192, "Dark", TextStyle { font_size: 20.0, left_padding: 80, top_padding: 22 }),
            (116, 117, 240, 80, 400, 192, "High Contrast", TextStyle { font_size: 20.0, left_padding: 52, top_padding: 22 }),
            (120, 121, 300, 44, 48, 288, "Temperature unit", TextStyle { font_size: 21.0, left_padding: 8, top_padding: 5 }),
            (124, 125, 240, 80, 80, 352, "Celsius", TextStyle { font_size: 20.0, left_padding: 74, top_padding: 22 }),
            (128, 129, 240, 80, 400, 352, "Fahrenheit", TextStyle { font_size: 20.0, left_padding: 62, top_padding: 22 }),
            (132, 133, 300, 44, 48, 448, "System information", TextStyle { font_size: 21.0, left_padding: 8, top_padding: 5 }),
            (136, 137, 608, 48, 56, 520, &build_line, TextStyle { font_size: 15.0, left_padding: 8, top_padding: 10 }),
            (140, 141, 608, 48, 56, 584, &product_line, TextStyle { font_size: 15.0, left_padding: 8, top_padding: 10 }),
            (144, 145, 608, 48, 56, 648, "Owner: build-info + hwinfo (read-only)", TextStyle { font_size: 15.0, left_padding: 8, top_padding: 10 }),
        ]
    };
    for (transform, content, width, height, x, y, text, style) in text_specs {
        match TextSurface::new_with_style(
            &flatland,
            &root,
            flatland::TransformId { value: transform },
            flatland::ContentId { value: content },
            fmath::SizeU { width, height },
            fmath::Vec_ { x, y },
            text,
            style,
        )
        .await
        {
            Ok(surface) => static_text.push(surface),
            Err(error) => warn!("Settings label {text:?} skipped: {error}"),
        }
    }

    let theme_value = TextSurface::new_with_style(
        &flatland,
        &root,
        flatland::TransformId { value: 200 },
        flatland::ContentId { value: 201 },
        fmath::SizeU { width: if narrow { 32 } else { 320 }, height: if narrow { 16 } else { 40 } },
        fmath::Vec_ { x: if narrow { -80 } else { 352 }, y: if narrow { -80 } else { 124 } },
        &format!("Current: {}", controller.theme().label()),
        TextStyle { font_size: 16.0, left_padding: 8, top_padding: 8 },
    )
    .await?;
    let temperature_value = if intl_proxy.is_some() {
        Some(
            TextSurface::new_with_style(
                &flatland,
                &root,
                flatland::TransformId { value: 204 },
                flatland::ContentId { value: 205 },
                fmath::SizeU { width: 320, height: 40 },
                fmath::Vec_ { x: 352, y: 292 },
                &format!("Current: {}", controller.temperature().label()),
                TextStyle { font_size: 16.0, left_padding: 8, top_padding: 8 },
            )
            .await?,
        )
    } else {
        None
    };
    let status = TextSurface::new_with_style(
        &flatland,
        &root,
        flatland::TransformId { value: 208 },
        flatland::ContentId { value: 209 },
        fmath::SizeU { width: status_w, height: status_h },
        fmath::Vec_ { x: 8, y: if narrow { status_y } else { size.height.saturating_sub(88) as i32 } },
        controller.status(),
        TextStyle { font_size: 16.0, left_padding: 8, top_padding: 15 },
    )
    .await?;
    let mut dynamic = DynamicSurfaces { theme_value, temperature_value, status };
    refresh_ui(&flatland, &controller, &mut dynamic, metrics).await?;
    info!(
        "Presented Fuchsia Settings at {}x{} theme={} temperature={} hidden={:?}",
        size.width,
        size.height,
        controller.theme().label(),
        controller.temperature().label(),
        controller.hidden_controls()
    );
    info!("Settings owners: app=/data intl={} build={} product={}", owners.intl_service, owners.build_info, owners.product_info);
    if injected_failure {
        info!("Injected failure proof: {}", controller.status());
    }

    let (touch_sender, touch_events) = unbounded();
    fasync::Task::local(watch_touch_source(touch_source, touch_sender)).detach();
    let mut touch_events = touch_events.fuse();
    let mut flatland_events = flatland.take_event_stream().fuse();
    loop {
        futures::select! {
            position = touch_events.next() => {
                let Some([x, y]) = position else { break };
                let Some(action) = action_for_point(x, y, size.width as f32) else { continue };
                let action_name = format!("{action:?}");
                match action {
                    UiAction::ThemeDark => {
                        if let Err(error) = controller.set_theme(AppTheme::Dark) {
                            warn!("Settings action {action_name} failed: {error}");
                        }
                    }
                    UiAction::ThemeContrast => {
                        if let Err(error) = controller.set_theme(AppTheme::Contrast) {
                            warn!("Settings action {action_name} failed: {error}");
                        }
                    }
                    UiAction::TemperatureCelsius | UiAction::TemperatureFahrenheit => {
                        let target = if action == UiAction::TemperatureCelsius {
                            TemperatureUnit::Celsius
                        } else {
                            TemperatureUnit::Fahrenheit
                        };
                        let result = match intl_proxy.as_ref() {
                            Some(proxy) => apply_temperature(proxy, target).await,
                            None => Err("Intl service not available".to_string()),
                        };
                        if let Err(error) = controller.record_temperature_result(target, result) {
                            warn!("Settings action {action_name} failed: {error}");
                        }
                    }
                }
                info!("Settings action {action_name}: {}", controller.status());
                refresh_ui(&flatland, &controller, &mut dynamic, metrics).await?;
            }
            event = flatland_events.next() => match event {
                Some(Ok(flatland::FlatlandEvent::OnError { error })) => {
                    return Err(anyhow!("Flatland error: {error:?}"));
                }
                Some(Ok(_)) => {}
                Some(Err(error)) => return Err(error.into()),
                None => break,
            },
        }
    }
    drop((static_text, dynamic));
    Ok(())
}

async fn serve_view_provider(mut stream: ViewProviderRequestStream) -> Result<(), Error> {
    while let Some(request) = stream.try_next().await? {
        match request {
            ViewProviderRequest::CreateView2 { args, .. } => {
                let token = args
                    .view_creation_token
                    .ok_or_else(|| anyhow!("CreateView2 omitted view_creation_token"))?;
                Box::pin(create_settings_view(token)).await?;
            }
            other => warn!("Unsupported ViewProvider request: {other:?}"),
        }
    }
    Ok(())
}

#[fuchsia::main(logging = true)]
async fn main() -> Result<(), Error> {
    let mut fs = ServiceFs::new_local();
    fs.dir("svc").add_fidl_service(|stream: ViewProviderRequestStream| stream);
    fs.take_and_serve_directory_handle().context("serve ViewProvider")?;
    while let Some(stream) = fs.next().await {
        Box::pin(serve_view_provider(stream)).await?;
    }
    Ok(())
}
