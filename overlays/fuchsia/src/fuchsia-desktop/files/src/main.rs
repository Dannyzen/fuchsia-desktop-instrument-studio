// Copyright 2026 The Fuchsia Desktop Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

use anyhow::{anyhow, Context as _, Error};
use fidl::endpoints::create_proxy;
use fidl_fuchsia_math as fmath;
use fidl_fuchsia_ui_app::{ViewProviderRequest, ViewProviderRequestStream};
use fidl_fuchsia_ui_composition as flatland;
use fidl_fuchsia_ui_pointer as pointer;
use fidl_fuchsia_ui_views as views;
use fuchsia_async as fasync;
use fuchsia_component::{client::connect_to_protocol, server::ServiceFs};
use futures::channel::mpsc::{unbounded, UnboundedSender};
use futures::{StreamExt as _, TryStreamExt as _};
use log::{info, warn};

mod files_core;
mod files_ui;
mod text_surface;

use files_core::{Entry, EntryKind, FilesController, RootedFiles};
use files_ui::{action_for_point_in, UiAction, MAX_VISIBLE_ROWS, CELL_H, GRID_COLS, GRID_GAP, GRID_PAD, GRID_TOP};
use text_surface::{TextStyle, TextSurface};

const BACKGROUND: flatland::ColorRgba =
    flatland::ColorRgba { red: 0.035, green: 0.039, blue: 0.047, alpha: 1.0 };
const PANEL: flatland::ColorRgba =
    flatland::ColorRgba { red: 0.102, green: 0.110, blue: 0.129, alpha: 1.0 };
const SURFACE: flatland::ColorRgba =
    flatland::ColorRgba { red: 0.176, green: 0.188, blue: 0.216, alpha: 1.0 };
const SELECTED: flatland::ColorRgba =
    flatland::ColorRgba { red: 0.235, green: 0.251, blue: 0.286, alpha: 1.0 };
const ACCENT: flatland::ColorRgba =
    flatland::ColorRgba { red: 0.357, green: 0.784, blue: 0.839, alpha: 1.0 };
const DANGER: flatland::ColorRgba =
    flatland::ColorRgba { red: 0.925, green: 0.400, blue: 0.267, alpha: 1.0 };

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
                warn!("Files TouchSource closed: {error:?}");
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

fn row_label(entry: Option<&Entry>) -> String {
    match entry {
        Some(entry) => entry.name.clone(),
        None => String::new(),
    }
}

struct DynamicSurfaces {
    path: Option<TextSurface>,
    status: Option<TextSurface>,
    rows: Vec<TextSurface>,
}

async fn refresh_dynamic_ui(
    flatland: &flatland::FlatlandProxy,
    controller: &FilesController,
    surfaces: &mut DynamicSurfaces,
    status_override: Option<&str>,
    size_w: u32,
) -> Result<(), Error> {
    let current = controller.current_directory();
    let path = if current.is_empty() { "Files /".to_string() } else { format!("Files /{current}") };
    if let Some(surface) = surfaces.path.as_mut() {
        let _ = surface.update(flatland, &path).await;
    }
    let cell_w = ((size_w.saturating_sub((GRID_PAD * 2.0 + GRID_GAP) as u32)) / GRID_COLS as u32).max(72);
    for index in 0..MAX_VISIBLE_ROWS {
        let entry = controller.entries().get(index);
        if let Some(surface) = surfaces.rows.get_mut(index) {
            let _ = surface.update(flatland, &row_label(entry)).await;
        }
        let selected = entry
            .map(|entry| Some(entry.name.as_str()) == controller.selected_name())
            .unwrap_or(false);
        let _ = flatland.set_solid_fill(
            &flatland::ContentId { value: 201 + index as u64 * 2 },
            if selected { &SELECTED } else { &SURFACE },
            &fmath::SizeU { width: cell_w, height: CELL_H as u32 },
        );
    }
    let status = status_override.unwrap_or_else(|| controller.status());
    if let Some(surface) = surfaces.status.as_mut() {
        let _ = surface.update(flatland, status).await;
    }
    flatland.set_solid_fill(
        &flatland::ContentId { value: 33 },
        if controller.status().starts_with("Confirm delete") { &DANGER } else { &SURFACE },
        &fmath::SizeU { width: 88, height: 48 },
    )?;
    flatland.present(flatland::PresentArgs::default())?;
    Ok(())
}

fn apply_action(controller: &mut FilesController, action: UiAction) -> Result<(), String> {
    match action {
        UiAction::Up => controller.go_up(),
        UiAction::Open => controller.open_selected(),
        UiAction::Create => controller.create_file(),
        UiAction::Rename => controller.rename_selected(),
        UiAction::Copy => controller.copy_selected(),
        UiAction::Move => controller.move_selected(),
        UiAction::Delete => controller.delete_selected(),
        UiAction::Select(index) => {
            let name = controller
                .entries()
                .get(index)
                .map(|entry| entry.name.clone())
                .ok_or_else(|| format!("no entry in row {}", index + 1))?;
            controller.select(&name)
        }
    }
}

async fn create_files_view(root_token: views::ViewCreationToken) -> Result<(), Error> {
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
        fmath::SizeU { width: size.width, height: 72 },
        fmath::Vec_ { x: 0, y: 0 },
    )?;
    create_rect(
        &flatland,
        &root,
        6,
        7,
        &ACCENT,
        fmath::SizeU { width: 8, height: 72 },
        fmath::Vec_ { x: 0, y: 0 },
    )?;

    let narrow = size.width < 520 || (size.height > size.width && size.width < 800);
    let button_specs = if narrow {
        [
            (8, 72, "Up"),
            (84, 72, "Open"),
            (160, 72, "New"),
            (236, 80, "Ren"),
            (8, 72, "Copy"),
            (84, 72, "Move"),
            (160, 80, "Del"),
        ]
    } else {
        [
            (16, 72, "Up"),
            (96, 72, "Open"),
            (176, 72, "New"),
            (256, 88, "Rename"),
            (352, 72, "Copy"),
            (432, 72, "Move"),
            (512, 88, "Delete"),
        ]
    };
    let mut static_text = Vec::new();
    for (index, (x, width, label)) in button_specs.iter().enumerate() {
        let by = if narrow && index >= 4 { 140 } else { 88 };
        create_rect(
            &flatland,
            &root,
            20 + index as u64 * 2,
            21 + index as u64 * 2,
            &SURFACE,
            fmath::SizeU { width: *width, height: 48 },
            fmath::Vec_ { x: *x, y: by },
        )?;
        match TextSurface::new_with_style(
            &flatland,
            &root,
            flatland::TransformId { value: 100 + index as u64 * 4 },
            flatland::ContentId { value: 101 + index as u64 * 4 },
            fmath::SizeU { width: *width, height: 48 },
            fmath::Vec_ { x: *x, y: by },
            label,
            TextStyle { font_size: 15.0, left_padding: 8, top_padding: 11 },
        )
        .await
        {
            Ok(surface) => static_text.push(surface),
            Err(error) => warn!("Files toolbar label {label} skipped: {error}"),
        }
    }
    if let Err(error) = flatland.present(flatland::PresentArgs::default()) {
        warn!("Files toolbar present failed: {error:?}");
    }

    let cell_w = if narrow {
        size.width.saturating_sub((GRID_PAD * 2.0 + GRID_GAP) as u32) / GRID_COLS as u32
    } else {
        size.width.saturating_sub(24).max(80)
    };
    for index in 0..MAX_VISIBLE_ROWS {
        let (x, y) = if narrow {
            let col = (index % GRID_COLS) as u32;
            let row = (index / GRID_COLS) as u32;
            (
                GRID_PAD as i32 + (col as f32 * (cell_w as f32 + GRID_GAP)) as i32,
                GRID_TOP as i32 + (row as f32 * (CELL_H + GRID_GAP)) as i32,
            )
        } else {
            (12, 160 + index as i32 * 64)
        };
        create_rect(
            &flatland,
            &root,
            200 + index as u64 * 2,
            201 + index as u64 * 2,
            &SURFACE,
            fmath::SizeU { width: if narrow { cell_w.max(72) } else { size.width.saturating_sub(24).max(80) }, height: if narrow { CELL_H as u32 } else { 56 } },
            fmath::Vec_ { x, y },
        )?;
        if narrow {
            create_rect(
                &flatland,
                &root,
                700 + index as u64 * 2,
                701 + index as u64 * 2,
                &PANEL,
                fmath::SizeU { width: 36, height: 36 },
                fmath::Vec_ { x: x + (cell_w as i32 - 36) / 2, y: y + 8 },
            )?;
        }
    }
    create_rect(
        &flatland,
        &root,
        600,
        601,
        &PANEL,
        fmath::SizeU { width: size.width.saturating_sub(32), height: 64 },
        fmath::Vec_ { x: 16, y: size.height.saturating_sub(80) as i32 },
    )?;
    // Grid geometry first so a later TextSurface failure still shows icon cells.
    if let Err(error) = flatland.present(flatland::PresentArgs::default()) {
        warn!("Files geometry present failed: {error:?}");
    }
    info!("Presented Files geometry at {}x{}", size.width, size.height);

    let mut controller = match FilesController::new("/data") {
        Ok(controller) => Some(controller),
        Err(error) => {
            warn!("Files controller failed; geometry-only view stays up: {error}");
            None
        }
    };
    let title = match TextSurface::new_with_style(
        &flatland,
        &root,
        flatland::TransformId { value: 504 },
        flatland::ContentId { value: 505 },
        fmath::SizeU { width: 220, height: 48 },
        fmath::Vec_ { x: 24, y: 12 },
        "Files",
        TextStyle { font_size: 24.0, left_padding: 8, top_padding: 5 },
    )
    .await
    {
        Ok(surface) => Some(surface),
        Err(error) => {
            warn!("Files title skipped: {error}");
            None
        }
    };
    let path_surface = match TextSurface::new_with_style(
        &flatland,
        &root,
        flatland::TransformId { value: 500 },
        flatland::ContentId { value: 501 },
        fmath::SizeU { width: if narrow { size.width.saturating_sub(32).max(80) } else { 320 }, height: 40 },
        fmath::Vec_ { x: if narrow { 16 } else { 280 }, y: if narrow { 44 } else { 16 } },
        "Files /",
        TextStyle::ADDRESS,
    )
    .await
    {
        Ok(surface) => Some(surface),
        Err(error) => {
            warn!("Files path skipped: {error}");
            None
        }
    };
    let status_surface = match TextSurface::new_with_style(
        &flatland,
        &root,
        flatland::TransformId { value: 508 },
        flatland::ContentId { value: 509 },
        fmath::SizeU { width: size.width.saturating_sub(48), height: 48 },
        fmath::Vec_ { x: 24, y: size.height.saturating_sub(72) as i32 },
        controller.as_ref().map(|c| c.status()).unwrap_or("Ready"),
        TextStyle { font_size: 16.0, left_padding: 8, top_padding: 10 },
    )
    .await
    {
        Ok(surface) => Some(surface),
        Err(error) => {
            warn!("Files status skipped: {error}");
            None
        }
    };
    let mut row_surfaces = Vec::new();
    for index in 0..MAX_VISIBLE_ROWS {
        let (x, y, w, h, font, pad_top) = if narrow {
            let col = (index % GRID_COLS) as u32;
            let row = (index / GRID_COLS) as u32;
            let cx = GRID_PAD as i32 + (col as f32 * (cell_w as f32 + GRID_GAP)) as i32;
            let cy = GRID_TOP as i32 + (row as f32 * (CELL_H + GRID_GAP)) as i32;
            (cx + 4, cy + 48, cell_w.saturating_sub(8).max(48), 32, 11.0, 6)
        } else {
            (16, 160 + index as i32 * 64, size.width.saturating_sub(32).max(72), 56, 19.0, 12)
        };
        match TextSurface::new_with_style(
            &flatland,
            &root,
            flatland::TransformId { value: 300 + index as u64 * 4 },
            flatland::ContentId { value: 301 + index as u64 * 4 },
            fmath::SizeU { width: w, height: h },
            fmath::Vec_ { x, y },
            &row_label(controller.as_ref().and_then(|c| c.entries().get(index))),
            TextStyle { font_size: font, left_padding: 4, top_padding: pad_top },
        )
        .await
        {
            Ok(surface) => row_surfaces.push(surface),
            Err(error) => warn!("Files label {index} skipped: {error}"),
        }

    }
    let mut dynamic = DynamicSurfaces { path: path_surface, status: status_surface, rows: row_surfaces };
    if let Err(error) = flatland.present(flatland::PresentArgs::default()) {
        warn!("Files label present failed: {error:?}");
    }
    info!("Presented Fuchsia Files at {}x{} with bounded /data storage", size.width, size.height);
    let outside_probe = RootedFiles::new("/data")
        .and_then(|files| files.read_text("../outside"))
        .err()
        .unwrap_or_else(|| "unexpectedly accepted".to_string());
    info!("Rejected outside-root probe: {outside_probe}");

    let (touch_sender, touch_events) = unbounded();
    fasync::Task::local(watch_touch_source(touch_source, touch_sender)).detach();
    let mut touch_events = touch_events.fuse();
    let mut flatland_events = flatland.take_event_stream().fuse();
    loop {
        futures::select! {
            position = touch_events.next() => {
                // TouchSource close is not view death. Stay presented.
                let Some([x, y]) = position else { continue };
                if let Some(action) = action_for_point_in(x, y, size.width as f32) {
                    let Some(controller) = controller.as_mut() else {
                        warn!("Files action ignored: controller unavailable");
                        continue;
                    };
                    let action_name = format!("{action:?}");
                    let result = apply_action(controller, action);
                    match result {
                        Ok(()) => {
                            info!("Files action {action_name}: {}", controller.status());
                            refresh_dynamic_ui(&flatland, controller, &mut dynamic, None, size.width).await?;
                        }
                        Err(error) => {
                            warn!("Files action {action_name} failed: {error}");
                            refresh_dynamic_ui(
                                &flatland,
                                controller,
                                &mut dynamic,
                                Some(&format!("Error: {error}")),
                                size.width,
                            )
                            .await?;
                        }
                    }
                }
            }
            event = flatland_events.next() => match event {
                Some(Ok(flatland::FlatlandEvent::OnError { error })) => {
                    warn!("Files Flatland error (keeping view): {error:?}");
                }
                Some(Ok(_)) => {}
                Some(Err(error)) => warn!("Files Flatland stream error (keeping view): {error}"),
                None => {
                    warn!("Files Flatland stream closed; parking");
                    futures::future::pending::<()>().await;
                }
            },
        }
    }
    drop((title, static_text, dynamic));
    Ok(())
}

async fn serve_view_provider(mut stream: ViewProviderRequestStream) -> Result<(), Error> {
    while let Some(request) = stream.try_next().await? {
        match request {
            ViewProviderRequest::CreateView2 { args, .. } => {
                let token = args
                    .view_creation_token
                    .ok_or_else(|| anyhow!("CreateView2 omitted view_creation_token"))?;
                if let Err(error) = Box::pin(create_files_view(token)).await {
                    warn!("Files create_view failed; staying running: {error:#}");
                }
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
