// Copyright 2023 The Fuchsia Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

use anyhow::{Context, Error};
use fidl::endpoints::{Proxy, RequestStream, create_proxy};
use fidl_fuchsia_element as element;
use fidl_fuchsia_session_scene as scene;
use fidl_fuchsia_session_window as window;
use fidl_fuchsia_ui_composition as ui_comp;
use fidl_fuchsia_ui_focus as ui_focus;
use fidl_fuchsia_ui_views as ui_views;
use fidl_fuchsia_ui_views_ext::ViewRefExt as _;
use fuchsia_async as fasync;
use fuchsia_component::client::connect_to_protocol;
use fuchsia_component::server::{ServiceFs, ServiceObj};
use fuchsia_scenic::ViewRefPair;
use fuchsia_scenic::flatland::{IdGenerator, ViewCreationTokenPair};
use futures::channel::mpsc::UnboundedSender;
use futures::{StreamExt, TryStreamExt};
use fuchsia_inspect::component;
use fuchsia_inspect::health::Reporter;
use log::{error, info, warn};
use rand::distr::{Alphanumeric, SampleString};
use rand::rng;
use std::collections::HashMap;

mod chrome;
mod chrome_text;
mod observability;
mod policy;

use chrome::{ChromeState, ShellChrome};
use desktop_ui::{ChromeRegion, InstrumentStudioLayout};
use observability::WmObservability;
use policy::{LayoutConfig, Size, WindowPolicy, compute_layout};

// The maximum number of concurrent services to serve.
const NUM_CONCURRENT_REQUESTS: usize = 5;

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct TileId(pub String);

fn tile_short_label(id: &str) -> &'static str {
    let key = id.to_ascii_lowercase();
    // "settings" must win before "files": the word settings contains no
    // "files" substring, but session names can include both tokens.
    if key.contains("settings") {
        "Settings"
    } else if key.contains("files") {
        "Files"
    } else if key.contains("browser") {
        "Browser"
    } else if key.contains("terminal") {
        "Terminal"
    } else {
        "APP"
    }
}

fn desktop_ui_tile_title(
    id: &str,
    stage_x: u32,
    stage_y: u32,
    slot: &policy::LayoutSlot,
    inset: u32,
    title_h: u32,
) -> chrome::TileTitle {
    chrome::TileTitle {
        x: (stage_x + slot.x + inset + 16) as i32,
        y: (stage_y + slot.y + inset + title_h.saturating_sub(21) / 2) as i32,
        label: tile_short_label(id).to_string(),
    }
}



fn tile_accent(id: &str) -> (f32, f32, f32) {
    let key = id.to_ascii_lowercase();
    if key.contains("settings") {
        (0.0, 0.92, 1.0)
    } else if key.contains("files") {
        (0.55, 0.49, 1.0)
    } else if key.contains("browser") {
        (0.94, 0.71, 0.16)
    } else if key.contains("terminal") {
        (0.24, 0.84, 0.55)
    } else {
        (0.60, 0.66, 0.72)
    }
}


impl std::fmt::Display for TileId {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "id={}", self.0)
    }
}

fn view_name_from_annotations(annotations: Option<&[element::Annotation]>) -> Option<String> {
    annotations?.iter().find_map(|annotation| {
        if annotation.key.namespace == element::MANAGER_NAMESPACE
            && annotation.key.value == element::ANNOTATION_KEY_NAME
        {
            match &annotation.value {
                element::AnnotationValue::Text(value) if !value.is_empty() => Some(value.clone()),
                _ => None,
            }
        } else {
            None
        }
    })
}

pub enum MessageInternal {
    GraphicalPresenterPresentView {
        view_spec: element::ViewSpec,
        annotation_controller: Option<element::AnnotationControllerProxy>,
        view_controller_request_stream: Option<element::ViewControllerRequestStream>,
        responder: element::GraphicalPresenterPresentViewResponder,
    },
    DismissClient {
        tile_id: TileId,
        control_handle: element::ViewControllerControlHandle,
    },
    ClientDied {
        tile_id: TileId,
    },
    ReceivedClientViewRef {
        tile_id: TileId,
        view_ref: ui_views::ViewRef,
    },
    WindowManagerListViews {
        responder: window::ManagerListResponder,
    },
    WindowManagerSetOrder {
        old_position: usize,
        new_position: usize,
        responder: window::ManagerSetOrderResponder,
    },
    WindowManagerCycle {
        responder: window::ManagerCycleResponder,
    },
    WindowManagerFocusView {
        position: usize,
        responder: window::ManagerFocusResponder,
    },
    FocusChainChanged {
        focused_koid: Option<zx::Koid>,
    },
}

struct ChildView {
    border_transform_id: ui_comp::TransformId,
    border_content_id: ui_comp::ContentId,
    viewport_transform_id: ui_comp::TransformId,
    viewport_content_id: ui_comp::ContentId,
    title_transform_id: ui_comp::TransformId,
    title_content_id: ui_comp::ContentId,
    accent_transform_id: ui_comp::TransformId,
    accent_content_id: ui_comp::ContentId,
    name: chrome::TileName,
    view_ref: Option<ui_views::ViewRef>,
    view_ref_koid: Option<zx::Koid>,
}

pub struct TilingWm {
    internal_sender: UnboundedSender<MessageInternal>,
    flatland: ui_comp::FlatlandProxy,
    id_generator: IdGenerator,
    view_focuser: ui_views::FocuserProxy,
    root_transform_id: ui_comp::TransformId,
    layout_info: ui_comp::LayoutInfo,
    layout_config: LayoutConfig,
    tiles: HashMap<TileId, ChildView>,
    policy: WindowPolicy,
    observability: WmObservability,
    chrome: ShellChrome,
}

impl Drop for TilingWm {
    fn drop(&mut self) {
        info!("dropping TilingWm");
        let flatland = &self.flatland;
        let tiles = &mut self.tiles;
        tiles.retain(|key, tile| {
            if let Err(e) = Self::release_tile_resources(flatland, tile) {
                error!("Error releasing resources for tile {key}: {e}");
            }
            false
        });
        if let Err(e) = flatland.clear() {
            error!("Error clearing Flatland: {e}");
        }
    }
}

impl TilingWm {
    async fn handle_message(&mut self, message: MessageInternal) -> Result<(), Error> {
        match message {
            // The ElementManager has asked us (via GraphicalPresenter::PresentView()) to display
            // the view provided by a newly-launched element.
            MessageInternal::GraphicalPresenterPresentView {
                view_spec,
                annotation_controller,
                view_controller_request_stream,
                responder,
            } => {
                // We have either a view holder token OR a viewport_creation_token, but for
                // Flatland we can expect a viewport creation token.
                let viewport_creation_token = match view_spec.viewport_creation_token {
                    Some(token) => token,
                    None => {
                        warn!(
                            "Client attempted to present Gfx component but only Flatland is \
                             supported."
                        );
                        return Ok(());
                    }
                };

                let requested_name = view_name_from_annotations(view_spec.annotations.as_deref());
                let new_tile_id = self.unique_tile_id(requested_name);

                // Group a filled focus ring and inset child viewport under one transform.
                let border_transform_id = self.id_generator.next_transform_id();
                let border_content_id = self.id_generator.next_content_id();
                self.flatland
                    .create_transform(&border_transform_id)
                    .context("GraphicalPresenterPresentView create border transform")?;
                self.flatland
                    .create_filled_rect(&border_content_id)
                    .context("GraphicalPresenterPresentView create border rect")?;
                self.flatland
                    .set_content(&border_transform_id, &border_content_id)
                    .context("GraphicalPresenterPresentView attach border rect")?;
                self.flatland
                    .add_child(&self.root_transform_id, &border_transform_id)
                    .context("GraphicalPresenterPresentView attach tile group")?;

                let (tile_watcher, tile_watcher_request) =
                    create_proxy::<ui_comp::ChildViewWatcherMarker>();
                let viewport_content_id = self.id_generator.next_content_id();
                let viewport_properties = ui_comp::ViewportProperties {
                    logical_size: Some(self.layout_info.logical_size.unwrap()),
                    ..Default::default()
                };
                self.flatland
                    .create_viewport(
                        &viewport_content_id,
                        viewport_creation_token,
                        &viewport_properties,
                        tile_watcher_request,
                    )
                    .context("GraphicalPresenterPresentView create viewport")?;
                let viewport_transform_id = self.id_generator.next_transform_id();
                self.flatland
                    .create_transform(&viewport_transform_id)
                    .context("GraphicalPresenterPresentView create viewport transform")?;
                self.flatland
                    .set_content(&viewport_transform_id, &viewport_content_id)
                    .context("GraphicalPresenterPresentView attach viewport")?;
                self.flatland
                    .add_child(&border_transform_id, &viewport_transform_id)
                    .context("GraphicalPresenterPresentView attach viewport to tile group")?;

                let title_transform_id = self.id_generator.next_transform_id();
                let title_content_id = self.id_generator.next_content_id();
                self.flatland.create_transform(&title_transform_id)?;
                self.flatland.create_filled_rect(&title_content_id)?;
                self.flatland.set_content(&title_transform_id, &title_content_id)?;
                self.flatland.add_child(&border_transform_id, &title_transform_id)?;
                let accent_transform_id = self.id_generator.next_transform_id();
                let accent_content_id = self.id_generator.next_content_id();
                self.flatland.create_transform(&accent_transform_id)?;
                self.flatland.create_filled_rect(&accent_content_id)?;
                self.flatland.set_content(&accent_transform_id, &accent_content_id)?;
                self.flatland.add_child(&title_transform_id, &accent_transform_id)?;
                // Names last so they paint above the header wash and accent rail.
                let name = chrome::TileName::create(
                    &self.flatland,
                    &mut self.id_generator,
                    &title_transform_id,
                    tile_short_label(&new_tile_id.0),
                )
                .await?;

                let new_tile = ChildView {
                    border_transform_id,
                    border_content_id,
                    viewport_transform_id,
                    viewport_content_id,
                    title_transform_id,
                    title_content_id,
                    accent_transform_id,
                    accent_content_id,
                    name,
                    view_ref: None,
                    view_ref_koid: None,
                };
                self.tiles.insert(new_tile_id.clone(), new_tile);
                self.policy.add_front(new_tile_id.0.clone());
                self.layout_tiles()?;
                self.present("GraphicalPresenterPresentView")?;

                // Alert the client that the view has been presented, then begin servicing ViewController requests.
                if view_controller_request_stream.is_some() {
                    let view_controller_request_stream = view_controller_request_stream.unwrap();
                    view_controller_request_stream
                        .control_handle()
                        .send_on_presented()
                        .context("GraphicalPresenterPresentView send_on_presented")?;
                    run_tile_controller_request_stream(
                        new_tile_id.clone(),
                        view_controller_request_stream,
                        self.internal_sender.clone(),
                    );
                }

                // Begin servicing ChildViewWatcher requests.
                Self::watch_tile(new_tile_id, tile_watcher, self.internal_sender.clone());

                // Ignore Annotations for now.
                let _ = annotation_controller;

                // Finally, acknowledge the PresentView request.
                if let Err(e) = responder.send(Ok(())) {
                    error!("Failed to send response for GraphicalPresenter.PresentView(): {}", e);
                }

                Ok(())
            }
            MessageInternal::DismissClient { tile_id, control_handle } => {
                control_handle.shutdown_with_epitaph(Ok(()));
                self.remove_tile(&tile_id, "client requested dismiss").await?;
                Ok(())
            }
            MessageInternal::ClientDied { tile_id } => {
                self.remove_tile(&tile_id, "client died").await?;
                Ok(())
            }
            MessageInternal::ReceivedClientViewRef { tile_id, view_ref, .. } => {
                let koid = view_ref.get_koid().context("read child ViewRef KOID")?;
                let tile = self
                    .tiles
                    .get_mut(&tile_id)
                    .with_context(|| format!("received ViewRef for unknown tile {tile_id}"))?;
                tile.view_ref_koid = Some(koid);
                tile.view_ref = Some(view_ref);

                // Focus the first accepted window only. Later windows wait for explicit policy or
                // pointer focus so launch order does not continually steal keyboard focus.
                if self.policy.focused_id() == Some(tile_id.0.as_str()) {
                    if let Err(error) = self.request_focus(&tile_id).await {
                        warn!("Initial focus request failed for {tile_id}: {error:#}");
                    }
                }
                Ok(())
            }
            MessageInternal::WindowManagerListViews { responder } => {
                let views = self.list_views();
                if let Err(e) = responder.send(&views) {
                    error!("Failed to send response for WindowManager Manager.List(): {}", e);
                }
                Ok(())
            }
            MessageInternal::WindowManagerSetOrder { old_position, new_position, responder } => {
                if let Err(error) = self.policy.set_order(old_position, new_position) {
                    warn!("WindowManager SetOrder rejected: {error}");
                } else {
                    self.layout_tiles()?;
                    self.present("WindowManagerSetOrder")?;
                    info!("TILING_WM_ORDER ids={}", self.policy.order().join(","));
                }
                if let Err(e) = responder.send() {
                    error!("Failed to send response for WindowManager Manager.SetOrder(): {e}");
                }
                Ok(())
            }
            MessageInternal::WindowManagerCycle { responder } => {
                if let Err(error) = self.policy.cycle_order() {
                    warn!("WindowManager Cycle rejected: {error}");
                } else {
                    self.layout_tiles()?;
                    self.present("WindowManagerCycle")?;
                    info!("TILING_WM_ORDER ids={}", self.policy.order().join(","));
                }
                if let Err(e) = responder.send() {
                    error!("Failed to send response for WindowManager Manager.Cycle(): {e}");
                }
                Ok(())
            }
            MessageInternal::WindowManagerFocusView { position, responder } => {
                if let Err(error) = self.focus_position(position).await {
                    warn!("WindowManager Focus rejected: {error}");
                }
                if let Err(e) = responder.send() {
                    error!("Failed to send response for WindowManager Manager.Focus(): {e}");
                }
                Ok(())
            }
            MessageInternal::FocusChainChanged { focused_koid } => {
                self.confirm_focus(focused_koid)?;
                Ok(())
            }
        }
    }

    pub async fn new(
        internal_sender: UnboundedSender<MessageInternal>,
        layout_config: LayoutConfig,
    ) -> Result<TilingWm, Error> {
        // TODO(https://fxbug.dev/42169911): do something like this to instantiate the library component that knows
        // how to generate a Flatland scene to lay views out on a tiled grid.  It will be used in the
        // event loop below.
        // let tiles_helper = tile_helper::TilesHelper::new();

        // Set the root view and then wait for scene_manager to reply with a CreateView2 request.
        // Don't await the result yet, because the future will not resolve until we handle the
        // ViewProvider request below.
        let scene_manager = connect_to_protocol::<scene::ManagerMarker>()
            .expect("failed to connect to fuchsia.scene.Manager");

        // TODO(https://fxbug.dev/42055565): see scene_manager.fidl.  If we awaited the future immediately we
        // would deadlock.  Conversely, if we just dropped the future, then scene_manager would barf
        // because it would try to reply to present_root_view() on a closed channel.  So we kick off
        // the async FIDL request (which is not idiomatic for Rust, where typically the "future
        // doesn't do anything" until awaited), and then call create_wm() so
        // that present_root_view() eventually returns a result.
        let ViewCreationTokenPair { view_creation_token, viewport_creation_token } =
            ViewCreationTokenPair::new()?;
        let fut = scene_manager.present_root_view(viewport_creation_token);
        let wm = Self::create_wm(view_creation_token, internal_sender, layout_config).await?;
        let _ = fut.await?;
        Ok(wm)
    }

    fn unique_tile_id(&self, requested_name: Option<String>) -> TileId {
        let mut base = requested_name.unwrap_or_else(|| {
            let mut generated = Alphanumeric.sample_string(&mut rng(), 16);
            generated.make_ascii_lowercase();
            generated
        });
        if base.is_empty() {
            base = "view".to_string();
        }
        if !self.tiles.contains_key(&TileId(base.clone())) {
            return TileId(base);
        }
        for suffix in 2.. {
            let candidate = TileId(format!("{base}-{suffix}"));
            if !self.tiles.contains_key(&candidate) {
                return candidate;
            }
        }
        unreachable!()
    }

    async fn remove_tile(&mut self, tile_id: &TileId, reason: &str) -> Result<(), Error> {
        let removed_confirmed = self.policy.confirmed_focus_id() == Some(tile_id.0.as_str());
        self.policy.remove(&tile_id.0);
        match self.tiles.remove(tile_id) {
            Some(mut tile) => {
                Self::release_tile_resources(&self.flatland, &mut tile)
                    .with_context(|| format!("release resources after {reason}: {tile_id}"))?;
                self.layout_tiles()?;
                self.present("RemoveTile")?;
                info!("TILING_WM_REMOVE id={} remaining={}", tile_id.0, self.policy.order().len());
                if removed_confirmed {
                    info!("TILING_WM_ACTIVE_CLEARED reason=removed id={}", tile_id.0);
                    if let Some(successor) =
                        self.policy.focused_id().map(|id| TileId(id.to_string()))
                    {
                        if let Err(error) = self.request_focus(&successor).await {
                            warn!(
                                "Successor focus request failed after removing {tile_id}; active ring remains cleared: {error:#}"
                            );
                        }
                    }
                }
            }
            None => warn!("Tile already absent after {reason}: {tile_id}"),
        }
        Ok(())
    }

    async fn request_focus(&self, tile_id: &TileId) -> Result<(), Error> {
        let tile = self.tiles.get(tile_id).with_context(|| format!("unknown tile {tile_id}"))?;
        let view_ref = tile
            .view_ref
            .as_ref()
            .with_context(|| format!("tile is not focusable yet: {tile_id}"))?;
        let duplicate = fuchsia_scenic::duplicate_view_ref(view_ref)
            .with_context(|| format!("duplicate ViewRef for {tile_id}"))?;
        match self.view_focuser.request_focus(duplicate).await {
            Ok(Ok(())) => {
                info!("Requested focus on child {tile_id}");
                Ok(())
            }
            Ok(Err(error)) => Err(anyhow::anyhow!("focus denied for {tile_id}: {error:?}")),
            Err(error) => Err(anyhow::anyhow!("focus transport failed for {tile_id}: {error}")),
        }
    }

    async fn focus_position(&mut self, position: usize) -> Result<(), Error> {
        let tile_id = self
            .policy
            .order()
            .get(position)
            .map(|id| TileId((*id).to_string()))
            .with_context(|| format!("focus position {position} is out of bounds"))?;
        self.request_focus(&tile_id).await
    }

    fn confirm_focus(&mut self, focused_koid: Option<zx::Koid>) -> Result<(), Error> {
        let focused_id = focused_koid.and_then(|focused_koid| {
            self.tiles.iter().find_map(|(tile_id, tile)| {
                (tile.view_ref_koid == Some(focused_koid)).then(|| tile_id.clone())
            })
        });
        let next_confirmed = focused_id.as_ref().map(|id| id.0.as_str());
        if self.policy.confirmed_focus_id() == next_confirmed {
            return Ok(());
        }
        match focused_id {
            Some(focused_id) => {
                self.policy.confirm_focus(&focused_id.0).map_err(anyhow::Error::msg)?;
                let position = self
                    .policy
                    .order()
                    .iter()
                    .position(|id| *id == focused_id.0)
                    .context("focused tile missing from policy order")?;
                self.layout_tiles()?;
                self.present("FocusChainChanged")?;
                info!("TILING_WM_ACTIVE id={} position={position}", focused_id.0);
            }
            None => {
                self.policy.clear_confirmed_focus();
                self.layout_tiles()?;
                self.present("FocusChainCleared")?;
                info!("TILING_WM_ACTIVE_CLEARED");
            }
        }
        Ok(())
    }

    fn publish_observability(&mut self, context: &str) {
        self.observability.publish_state(&self.policy, &self.layout_config);
        self.observability.record_present(context);
    }

    fn present(&mut self, context: &str) -> Result<(), Error> {
        if let Err(error) = self.flatland.present(ui_comp::PresentArgs {
            requested_presentation_time: Some(0),
            ..Default::default()
        }) {
            warn!("{context} present failed (continuing): {error}");
            return Ok(());
        }
        self.publish_observability(context);
        Ok(())
    }

    async fn create_wm(
        view_creation_token: ui_views::ViewCreationToken,
        internal_sender: UnboundedSender<MessageInternal>,
        layout_config: LayoutConfig,
    ) -> Result<TilingWm, Error> {
        let flatland = connect_to_protocol::<ui_comp::FlatlandMarker>()
            .expect("failed to connect to fuchsia.ui.flatland.Flatland");
        flatland.set_debug_name("TilingWM")?;

        let mut id_generator = IdGenerator::new();

        // Create the root transform for tiles.
        let root_transform_id = id_generator.next_transform_id();
        flatland.create_transform(&root_transform_id)?;
        flatland.set_root_transform(&root_transform_id)?;

        // Create the root view for tiles.
        let (parent_viewport_watcher, parent_viewport_watcher_request) =
            create_proxy::<ui_comp::ParentViewportWatcherMarker>();
        let (view_focuser, view_focuser_request) =
            fidl::endpoints::create_proxy::<ui_views::FocuserMarker>();
        let view_identity = ui_views::ViewIdentityOnCreation::from(ViewRefPair::new()?);
        let view_bound_protocols = ui_comp::ViewBoundProtocols {
            view_focuser: Some(view_focuser_request),
            ..Default::default()
        };
        flatland.create_view2(
            view_creation_token,
            view_identity,
            view_bound_protocols,
            parent_viewport_watcher_request,
        )?;

        // Present the root scene.
        flatland.present(ui_comp::PresentArgs {
            requested_presentation_time: Some(0),
            ..Default::default()
        })?;

        // Get initial layout deterministically before proceeding.
        // Begin servicing ParentViewportWatcher requests.
        let layout_info = parent_viewport_watcher.get_layout().await?;
        Self::watch_layout(parent_viewport_watcher, internal_sender.clone());

        let logical_size = layout_info.logical_size.context("missing initial root logical size")?;
        let shell = InstrumentStudioLayout::new(logical_size.width, logical_size.height)
            .map_err(anyhow::Error::msg)?;
        let chrome =
            ShellChrome::create(&flatland, &mut id_generator, &root_transform_id, &shell).await?;
        Ok(TilingWm {
            internal_sender,
            flatland,
            id_generator,
            view_focuser,
            root_transform_id,
            layout_info,
            layout_config,
            tiles: HashMap::new(),
            policy: WindowPolicy::new(layout_config).map_err(anyhow::Error::msg)?,
            observability: WmObservability::attach(component::inspector().root(), &layout_config),
            chrome,
        })
    }

    fn release_tile_resources(
        flatland: &ui_comp::FlatlandProxy,
        tile: &mut ChildView,
    ) -> Result<(), Error> {
        let _ = flatland.release_viewport(&tile.viewport_content_id);
        let _ = flatland.release_filled_rect(&tile.title_content_id);
        let _ = flatland.release_filled_rect(&tile.accent_content_id);
        flatland.release_filled_rect(&tile.border_content_id)?;
        flatland.release_transform(&tile.viewport_transform_id)?;
        flatland.release_transform(&tile.border_transform_id)?;
        Ok(())
    }

    fn list_views(&self) -> Vec<window::ListedView> {
        self.policy
            .order()
            .into_iter()
            .enumerate()
            .map(|(position, id)| window::ListedView {
                position: position as u64,
                id: id.to_string(),
            })
            .collect()
    }

    fn layout_tiles(&mut self) -> Result<(), Error> {
        let logical_size = self.layout_info.logical_size.context("missing root logical size")?;
        let shell = InstrumentStudioLayout::new(logical_size.width, logical_size.height)
            .map_err(anyhow::Error::msg)?;
        let stage = shell.region_rect(ChromeRegion::TiledStage);
        let order: Vec<String> = self.policy.order().into_iter().map(str::to_string).collect();
        let slots = compute_layout(
            Size { width: stage.width, height: stage.height },
            order.len(),
            self.layout_config,
        )
        .map_err(anyhow::Error::msg)?;
        let mut tile_titles = Vec::new();
        for (id, slot) in order.iter().zip(slots.iter()) {
            let inset = slot.content_inset;
            let title_h = 28u32.min(slot.height.saturating_sub(inset * 2).saturating_sub(8));
            tile_titles.push(desktop_ui_tile_title(id, stage.x, stage.y, slot, inset, title_h));
        }
        let chrome_state = ChromeState {
            tile_count: self.policy.order().len() as u32,
            confirmed_focus: self.policy.confirmed_focus_id().unwrap_or("").to_string(),
            order: order.clone(),
            gap_px: self.layout_config.gap_px,
            active_border_px: self.layout_config.active_border_px,
            present_count: self.observability.present_count_value,
            tile_titles,
        };
        self.chrome.layout(&self.flatland, &shell, &chrome_state)?;
        let active_id = self.policy.confirmed_focus_id().map(str::to_string);
        for (id, slot) in order.iter().zip(slots) {
            let tile_id = TileId(id.clone());
            let view = self
                .tiles
                .get_mut(&tile_id)
                .with_context(|| format!("policy references missing tile {tile_id}"))?;
            let border_size = fidl_fuchsia_math::SizeU { width: slot.width, height: slot.height };
            let color = if active_id.as_deref() == Some(id.as_str()) {
                ui_comp::ColorRgba { red: 0.0, green: 0.82, blue: 1.0, alpha: 1.0 }
            } else {
                ui_comp::ColorRgba { red: 0.10, green: 0.12, blue: 0.16, alpha: 1.0 }
            };
            self.flatland
                .set_solid_fill(&view.border_content_id, &color, &border_size)
                .context("set tile border fill")?;
            self.flatland
                .set_translation(
                    &view.border_transform_id,
                    &fidl_fuchsia_math::Vec_ {
                        x: (stage.x + slot.x) as i32,
                        y: (stage.y + slot.y) as i32,
                    },
                )
                .context("translate tile group")?;

            let inset = slot.content_inset;
            let title_h = 36u32.min(slot.height.saturating_sub(inset * 2).saturating_sub(8));
            let inner_w = slot.width.saturating_sub(inset * 2).max(1);
            let inner_h = slot.height.saturating_sub(inset * 2).max(1);
            let (ar, ag, ab) = tile_accent(&id);
            // Card header wash — darker panel with the app accent so tiles read as cards.
            self.flatland.set_solid_fill(
                &view.title_content_id,
                &ui_comp::ColorRgba { red: ar * 0.18, green: ag * 0.18, blue: ab * 0.22, alpha: 1.0 },
                &fidl_fuchsia_math::SizeU { width: inner_w, height: title_h },
            )?;
            self.flatland.set_translation(
                &view.title_transform_id,
                &fidl_fuchsia_math::Vec_ { x: inset as i32, y: inset as i32 },
            )?;
            // Left identity rail (design app-dot, but readable at FEMU scale).
            self.flatland.set_solid_fill(
                &view.accent_content_id,
                &ui_comp::ColorRgba { red: ar, green: ag, blue: ab, alpha: 1.0 },
                &fidl_fuchsia_math::SizeU { width: 8, height: title_h },
            )?;
            self.flatland.set_translation(
                &view.accent_transform_id,
                &fidl_fuchsia_math::Vec_ { x: 0, y: 0 },
            )?;
            let viewport_size = fidl_fuchsia_math::SizeU {
                width: inner_w,
                height: inner_h.saturating_sub(title_h).max(1),
            };
            self.flatland
                .set_viewport_properties(
                    &view.viewport_content_id,
                    &ui_comp::ViewportProperties {
                        logical_size: Some(viewport_size),
                        ..Default::default()
                    },
                )
                .context("set inset viewport properties")?;
            self.flatland
                .set_translation(
                    &view.viewport_transform_id,
                    &fidl_fuchsia_math::Vec_ { x: inset as i32, y: (inset + title_h) as i32 },
                )
                .context("translate inset viewport")?;
        }
        info!(
            "TILING_WM_CHROME stage={}x{}+{}+{} strip_h={} rail_w={} inspector_h={}",
            stage.width,
            stage.height,
            stage.x,
            stage.y,
            shell.theme.panel_height_px,
            shell.theme.rail_width_px,
            shell.theme.inspector_height_px
        );
        Ok(())
    }


    fn watch_layout(
        proxy: ui_comp::ParentViewportWatcherProxy,
        _internal_sender: UnboundedSender<MessageInternal>,
    ) {
        // Listen for channel closure.
        // TODO(https://fxbug.dev/42169911): Actually watch for and respond to layout changes.
        fasync::Task::local(async move {
            let _ = proxy.on_closed().await;
        })
        .detach();
    }

    fn watch_tile(
        tile_id: TileId,
        proxy: ui_comp::ChildViewWatcherProxy,
        internal_sender: UnboundedSender<MessageInternal>,
    ) {
        // Get view ref, then listen for channel closure.
        fasync::Task::local(async move {
            match proxy.get_view_ref().await {
                Ok(view_ref) => {
                    internal_sender
                        .unbounded_send(MessageInternal::ReceivedClientViewRef {
                            tile_id: tile_id.clone(),
                            view_ref,
                        })
                        .expect("Failed to send MessageInternal::ReceivedClientViewRef");
                }
                Err(error) => {
                    // Settings (and other heavy CreateView2 apps) can attach after
                    // the first GetLayout. A transient ViewRef miss is not death.
                    warn!("get_view_ref failed for {tile_id} (keeping tile): {error}");
                }
            }

            let _ = proxy.on_closed().await;

            internal_sender
                .unbounded_send(MessageInternal::ClientDied { tile_id })
                .expect("Failed to send MessageInternal::ClientDied");
        })
        .detach();
    }
}

enum ExposedServices {
    GraphicalPresenter(element::GraphicalPresenterRequestStream),
    WindowManager(window::ManagerRequestStream),
}

fn expose_services() -> Result<ServiceFs<ServiceObj<'static, ExposedServices>>, Error> {
    let mut fs = ServiceFs::new();

    // Add services for component outgoing directory.
    fs.dir("svc").add_fidl_service(ExposedServices::GraphicalPresenter);
    fs.dir("svc").add_fidl_service(ExposedServices::WindowManager);
    fs.take_and_serve_directory_handle()?;

    Ok(fs)
}

fn run_services(
    fs: ServiceFs<ServiceObj<'static, ExposedServices>>,
    internal_sender: UnboundedSender<MessageInternal>,
) {
    fasync::Task::local(async move {
        fs.for_each_concurrent(NUM_CONCURRENT_REQUESTS, |service_request: ExposedServices| async {
            match service_request {
                ExposedServices::GraphicalPresenter(request_stream) => {
                    run_graphical_presenter_service(request_stream, internal_sender.clone());
                }
                ExposedServices::WindowManager(request_stream) => {
                    run_window_manager_service(request_stream, internal_sender.clone());
                }
            }
        })
        .await;
    })
    .detach();
}

fn run_graphical_presenter_service(
    mut request_stream: element::GraphicalPresenterRequestStream,
    mut internal_sender: UnboundedSender<MessageInternal>,
) {
    fasync::Task::local(async move {
        loop {
            let result = request_stream.try_next().await;
            match result {
                Ok(Some(request)) => {
                    internal_sender = handle_graphical_presenter_request(request, internal_sender)
                }
                Ok(None) => {
                    info!("GraphicalPresenterRequestStream ended with Ok(None)");
                    return;
                }
                Err(e) => {
                    error!(
                        "Error while retrieving requests from GraphicalPresenterRequestStream: {}",
                        e
                    );
                    return;
                }
            }
        }
    })
    .detach();
}

fn handle_graphical_presenter_request(
    request: element::GraphicalPresenterRequest,
    internal_sender: UnboundedSender<MessageInternal>,
) -> UnboundedSender<MessageInternal> {
    match request {
        element::GraphicalPresenterRequest::PresentView {
            view_spec,
            annotation_controller,
            view_controller_request,
            responder,
        } => {
            // "Unwrap" the optional element::AnnotationControllerProxy.
            let annotation_controller = annotation_controller.map(|proxy| proxy.into_proxy());
            // "Unwrap" the optional element::ViewControllerRequestStream.
            let view_controller_request_stream =
                view_controller_request.map(|request_stream| request_stream.into_stream());
            internal_sender
                .unbounded_send(
                    MessageInternal::GraphicalPresenterPresentView {
                        view_spec,
                        annotation_controller,
                        view_controller_request_stream,
                        responder,
                    },
                    // TODO(https://fxbug.dev/42169911): is this a safe expect()?  I think so, since
                    // we're using Task::local() instead of Task::spawn(), so we're on the
                    // same thread as main(), which will keep the receiver end alive until
                    // it exits, at which time the executor will not tick this task again.
                    // Assuming that we verify this understanding, what is the appropriate
                    // way to document this understanding?  Is it so idiomatic it needs no
                    // comment?  We're all Rust n00bs here, so maybe not?
                )
                .expect("Failed to send MessageInternal.");
        }
    }
    return internal_sender;
}

// Serve the fuchsia.element.ViewController protocol. This merely redispatches
// the requests onto the `MessageInternal` handler, which are handled by
// `TilingWm::handle_message`.
pub fn run_tile_controller_request_stream(
    tile_id: TileId,
    mut request_stream: fidl_fuchsia_element::ViewControllerRequestStream,
    internal_sender: UnboundedSender<MessageInternal>,
) {
    fasync::Task::local(async move {
        if let Some(Ok(fidl_fuchsia_element::ViewControllerRequest::Dismiss { control_handle })) =
            request_stream.next().await
        {
            {
                internal_sender
                    .unbounded_send(MessageInternal::DismissClient { tile_id, control_handle })
                    .expect("Failed to send MessageInternal::DismissClient");
            }
        }
    })
    .detach();
}

fn run_window_manager_service(
    mut request_stream: window::ManagerRequestStream,
    mut internal_sender: UnboundedSender<MessageInternal>,
) {
    fasync::Task::local(async move {
        loop {
            let result = request_stream.try_next().await;
            match result {
                Ok(Some(request)) => {
                    internal_sender = handle_window_manager_request(request, internal_sender);
                }
                Ok(None) => {
                    info!("Window Manager ManagerRequestStream ended with Ok(None)");
                    return;
                }
                Err(e) => {
                    error!(
                        "Error while retrieving requests from Window Manager ManagerRequestStream: {}",
                        e
                    );
                    return;
                }
            }
        }
    })
    .detach();
}

fn handle_window_manager_request(
    request: window::ManagerRequest,
    internal_sender: UnboundedSender<MessageInternal>,
) -> UnboundedSender<MessageInternal> {
    match request {
        window::ManagerRequest::List { responder } => {
            internal_sender
                .unbounded_send(MessageInternal::WindowManagerListViews { responder })
                .expect("Failed to send MessageInternal.");
        }
        window::ManagerRequest::SetOrder { old_position, new_position, responder } => {
            internal_sender
                .unbounded_send(MessageInternal::WindowManagerSetOrder {
                    old_position: old_position as usize,
                    new_position: new_position as usize,
                    responder,
                })
                .expect("Failed to send MessageInternal.");
        }
        window::ManagerRequest::Cycle { responder } => {
            internal_sender
                .unbounded_send(MessageInternal::WindowManagerCycle { responder })
                .expect("Failed to send MessageInternal");
        }
        window::ManagerRequest::Focus { position, responder } => {
            internal_sender
                .unbounded_send(MessageInternal::WindowManagerFocusView {
                    position: position as usize,
                    responder,
                })
                .expect("Failed to send MessageInternal::WindowManagerFocusView");
        }
        _ => warn!("Ignoring unknown flexible fuchsia.session.window.Manager request"),
    }
    internal_sender
}

fn watch_focus_chain(internal_sender: UnboundedSender<MessageInternal>) -> Result<(), Error> {
    let registry = connect_to_protocol::<ui_focus::FocusChainListenerRegistryMarker>()
        .context("connect FocusChainListenerRegistry")?;
    let (listener_client, mut listener_stream) =
        fidl::endpoints::create_request_stream::<ui_focus::FocusChainListenerMarker>();
    registry.register(listener_client).context("register focus-chain listener")?;
    fasync::Task::local(async move {
        while let Some(request) = listener_stream.next().await {
            match request {
                Ok(ui_focus::FocusChainListenerRequest::OnFocusChange {
                    focus_chain,
                    responder,
                    ..
                }) => {
                    let focused_koid = focus_chain
                        .focus_chain
                        .as_ref()
                        .and_then(|chain| chain.last())
                        .and_then(|view_ref| view_ref.get_koid().ok());
                    if internal_sender
                        .unbounded_send(MessageInternal::FocusChainChanged { focused_koid })
                        .is_err()
                    {
                        return;
                    }
                    if let Err(error) = responder.send() {
                        error!("Failed to acknowledge focus-chain update: {error}");
                        return;
                    }
                }
                Err(error) => {
                    error!("Focus-chain listener failed: {error}");
                    return;
                }
            }
        }
    })
    .detach();
    Ok(())
}

#[fuchsia::main(logging = true)]
async fn main() -> Result<(), Error> {
    let inspector = component::inspector();
    component::health().set_ok();
    let _inspect_server_task =
        inspect_runtime::publish(inspector, inspect_runtime::PublishOptions::default());

    let config = tiling_wm_config::Config::take_from_startup_handle();
    let layout_config = LayoutConfig {
        gap_px: config.gap_px,
        active_border_px: config.active_border_px,
        wrap_focus: config.wrap_focus,
    };
    layout_config.validate().map_err(anyhow::Error::msg)?;

    let (internal_sender, mut internal_receiver) =
        futures::channel::mpsc::unbounded::<MessageInternal>();
    let fs = expose_services()?;
    watch_focus_chain(internal_sender.clone())?;

    // Connect to the scene owner and attach our tiles view to it.
    let mut wm = Box::new(TilingWm::new(internal_sender.clone(), layout_config).await?);

    // Serve the FIDL services on the message loop, proxying them into internal messages.
    run_services(fs, internal_sender.clone());

    // Process internal messages using tiling wm, then cleanup when done.
    while let Some(message) = internal_receiver.next().await {
        if let Err(e) = wm.handle_message(message).await {
            // A single PresentView / present-credit failure must not tear down the
            // desktop. Later session-add apps never become tiles if we break here.
            error!("Error handling message (continuing): {e}");
        }
    }

    Ok(())
}

#[cfg(test)]
mod identity_tests {
    use super::*;

    #[test]
    fn stable_name_comes_from_element_manager_annotation() {
        let annotations = vec![
            element::Annotation {
                key: element::AnnotationKey {
                    namespace: "other".to_string(),
                    value: "name".to_string(),
                },
                value: element::AnnotationValue::Text("ignore-me".to_string()),
            },
            element::Annotation {
                key: element::AnnotationKey {
                    namespace: element::MANAGER_NAMESPACE.to_string(),
                    value: element::ANNOTATION_KEY_NAME.to_string(),
                },
                value: element::AnnotationValue::Text("browser".to_string()),
            },
        ];
        assert_eq!(view_name_from_annotations(Some(&annotations)), Some("browser".to_string()));
    }

    #[test]
    fn missing_or_non_text_name_uses_no_stable_identity() {
        assert_eq!(view_name_from_annotations(None), None);
        let annotations = vec![element::Annotation {
            key: element::AnnotationKey {
                namespace: element::MANAGER_NAMESPACE.to_string(),
                value: element::ANNOTATION_KEY_URL.to_string(),
            },
            value: element::AnnotationValue::Text("fuchsia-pkg://example".to_string()),
        }];
        assert_eq!(view_name_from_annotations(Some(&annotations)), None);
    }
}
