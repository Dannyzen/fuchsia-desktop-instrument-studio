// Copyright 2026 The Fuchsia Desktop Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

use anyhow::{anyhow, Context as _, Error};
use fidl::endpoints::create_proxy;
use fidl_fuchsia_math as fmath;
use fidl_fuchsia_ui_app::{ViewProviderRequest, ViewProviderRequestStream};
use fidl_fuchsia_ui_composition as flatland;
use fidl_fuchsia_ui_views as views;
use fuchsia_component::{client::connect_to_protocol, server::ServiceFs};
use futures::{StreamExt, TryStreamExt};
use log::{info, warn};

mod text_surface;
use text_surface::{TextStyle, TextSurface};

const BACKGROUND: flatland::ColorRgba =
    flatland::ColorRgba { red: 0.035, green: 0.039, blue: 0.047, alpha: 1.0 };
const PANEL: flatland::ColorRgba =
    flatland::ColorRgba { red: 0.102, green: 0.110, blue: 0.129, alpha: 1.0 };
const SURFACE: flatland::ColorRgba =
    flatland::ColorRgba { red: 0.176, green: 0.188, blue: 0.216, alpha: 1.0 };
const SURFACE_ACTIVE: flatland::ColorRgba =
    flatland::ColorRgba { red: 0.235, green: 0.251, blue: 0.286, alpha: 1.0 };
const ACCENT: flatland::ColorRgba =
    flatland::ColorRgba { red: 0.357, green: 0.784, blue: 0.839, alpha: 1.0 };
const GREEN: flatland::ColorRgba =
    flatland::ColorRgba { red: 0.357, green: 0.745, blue: 0.467, alpha: 1.0 };
const ORANGE: flatland::ColorRgba =
    flatland::ColorRgba { red: 0.925, green: 0.545, blue: 0.267, alpha: 1.0 };

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

async fn add_text(
    surfaces: &mut Vec<TextSurface>,
    flatland: &flatland::FlatlandProxy,
    root: &flatland::TransformId,
    id: u64,
    x: i32,
    y: i32,
    width: u32,
    height: u32,
    label: &str,
    font_size: f32,
) -> Result<(), Error> {
    surfaces.push(
        TextSurface::new_with_style(
            flatland,
            root,
            flatland::TransformId { value: id },
            flatland::ContentId { value: id + 1 },
            fmath::SizeU { width, height },
            fmath::Vec_ { x, y },
            label,
            TextStyle { font_size, left_padding: 8, top_padding: 4 },
        )
        .await?,
    );
    Ok(())
}

async fn create_panel_view(root_token: views::ViewCreationToken) -> Result<(), Error> {
    let flatland = connect_to_protocol::<flatland::FlatlandMarker>()
        .context("connect to Flatland")?;
    let (parent_watcher, parent_watcher_server) =
        create_proxy::<flatland::ParentViewportWatcherMarker>();
    let view_ref_pair = fuchsia_scenic::ViewRefPair::new()?;
    flatland.r#create_view2(
        root_token,
        views::ViewIdentityOnCreation::from(view_ref_pair),
        flatland::ViewBoundProtocols::default(),
        parent_watcher_server,
    )?;
    let layout = parent_watcher.r#get_layout().await?;
    let size = layout.logical_size.ok_or_else(|| anyhow!("parent supplied no logical size"))?;

    let root = flatland::TransformId { value: 1 };
    flatland.create_transform(&root)?;
    flatland.set_root_transform(&root)?;
    create_rect(&flatland, &root, 2, 3, &BACKGROUND, size, fmath::Vec_ { x: 0, y: 0 })?;

    let panel_margin = 16u32;
    let panel_width = size.width.saturating_sub(panel_margin * 2).max(1);
    create_rect(
        &flatland,
        &root,
        4,
        5,
        &PANEL,
        fmath::SizeU { width: panel_width, height: 64 },
        fmath::Vec_ { x: panel_margin as i32, y: 16 },
    )?;
    create_rect(
        &flatland,
        &root,
        6,
        7,
        &ACCENT,
        fmath::SizeU { width: 40, height: 40 },
        fmath::Vec_ { x: 28, y: 28 },
    )?;
    create_rect(
        &flatland,
        &root,
        8,
        9,
        &SURFACE_ACTIVE,
        fmath::SizeU { width: 120, height: 40 },
        fmath::Vec_ { x: 340, y: 28 },
    )?;
    create_rect(
        &flatland,
        &root,
        10,
        11,
        &SURFACE,
        fmath::SizeU { width: 112, height: 40 },
        fmath::Vec_ { x: size.width.saturating_sub(140) as i32, y: 28 },
    )?;

    let card_width = size.width.saturating_sub(64).max(1);
    let card_top = 136i32;
    create_rect(
        &flatland,
        &root,
        20,
        21,
        &PANEL,
        fmath::SizeU { width: card_width, height: 108 },
        fmath::Vec_ { x: 32, y: card_top },
    )?;
    create_rect(
        &flatland,
        &root,
        22,
        23,
        &ACCENT,
        fmath::SizeU { width: 8, height: 108 },
        fmath::Vec_ { x: 32, y: card_top },
    )?;
    create_rect(
        &flatland,
        &root,
        24,
        25,
        &PANEL,
        fmath::SizeU { width: card_width, height: 108 },
        fmath::Vec_ { x: 32, y: card_top + 124 },
    )?;
    create_rect(
        &flatland,
        &root,
        26,
        27,
        &GREEN,
        fmath::SizeU { width: 8, height: 108 },
        fmath::Vec_ { x: 32, y: card_top + 124 },
    )?;

    let dock_width = size.width.saturating_sub(128).max(1);
    let dock_y = size.height.saturating_sub(104) as i32;
    create_rect(
        &flatland,
        &root,
        30,
        31,
        &PANEL,
        fmath::SizeU { width: dock_width, height: 72 },
        fmath::Vec_ { x: 64, y: dock_y },
    )?;
    for (index, color) in [ACCENT, GREEN, ORANGE, SURFACE_ACTIVE].iter().enumerate() {
        create_rect(
            &flatland,
            &root,
            40 + (index as u64 * 2),
            41 + (index as u64 * 2),
            color,
            fmath::SizeU { width: 44, height: 44 },
            fmath::Vec_ { x: 96 + index as i32 * 72, y: dock_y + 14 },
        )?;
    }

    let mut surfaces = Vec::new();
    add_text(&mut surfaces, &flatland, &root, 100, 76, 30, 240, 38, "COSMIC / Fuchsia", 20.0).await?;
    add_text(&mut surfaces, &flatland, &root, 104, 348, 34, 100, 28, "Workspace 1", 13.0).await?;
    add_text(
        &mut surfaces,
        &flatland,
        &root,
        108,
        size.width.saturating_sub(132) as i32,
        34,
        96,
        28,
        "Connected",
        13.0,
    )
    .await?;
    add_text(&mut surfaces, &flatland, &root, 112, 56, card_top + 14, card_width - 24, 34, "Browser", 23.0).await?;
    add_text(&mut surfaces, &flatland, &root, 116, 56, card_top + 54, card_width - 24, 28, "Native chrome + WebEngine", 15.0).await?;
    add_text(&mut surfaces, &flatland, &root, 120, 56, card_top + 138, card_width - 24, 34, "Terminal", 23.0).await?;
    add_text(&mut surfaces, &flatland, &root, 124, 56, card_top + 178, card_width - 24, 28, "Bounded shell + PTY", 15.0).await?;
    add_text(
        &mut surfaces,
        &flatland,
        &root,
        128,
        32,
        size.height.saturating_sub(160) as i32,
        size.width.saturating_sub(64),
        32,
        "Native Flatland shell spike",
        18.0,
    )
    .await?;

    flatland.present(flatland::PresentArgs::default())?;
    info!("Presented COSMIC-derived native panel at {}x{}", size.width, size.height);

    let mut events = flatland.take_event_stream();
    while let Some(event) = events.next().await {
        match event? {
            flatland::FlatlandEvent::OnError { error } => {
                return Err(anyhow!("Flatland error: {error:?}"));
            }
            _ => {}
        }
    }
    drop(surfaces);
    Ok(())
}

async fn serve_view_provider(mut stream: ViewProviderRequestStream) -> Result<(), Error> {
    while let Some(request) = stream.try_next().await? {
        match request {
            ViewProviderRequest::CreateView2 { args, .. } => {
                let token = args
                    .view_creation_token
                    .ok_or_else(|| anyhow!("CreateView2 omitted view_creation_token"))?;
                create_panel_view(token).await?;
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
        serve_view_provider(stream).await?;
    }
    Ok(())
}
