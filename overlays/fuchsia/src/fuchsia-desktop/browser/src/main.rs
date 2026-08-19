// Copyright 2026 The Fuchsia Desktop Authors.
// Use of this source code is governed by a BSD-style license.

use anyhow::{anyhow, Context, Error};
use fidl::endpoints::{create_proxy, create_request_stream, ClientEnd, Proxy};
use fidl_fuchsia_io as fio;
use fidl_fuchsia_math as fmath;
use fidl_fuchsia_ui_app::{ViewProviderRequest, ViewProviderRequestStream};
use fidl_fuchsia_ui_composition as flatland;
use fidl_fuchsia_ui_input3 as input3;
use fidl_fuchsia_ui_pointer as pointer;
use fidl_fuchsia_ui_views as views;
use fidl_fuchsia_web as web;
use config::Config;
use fuchsia_async as fasync;
use fuchsia_component::{client::connect_to_protocol, server::ServiceFs};
use fuchsia_scenic::flatland::ViewCreationTokenPair;
use futures::{StreamExt, TryStreamExt};
use futures::channel::mpsc::{UnboundedSender, unbounded};
use log::{info, warn};

mod text_surface;
use text_surface::{TextStyle, TextSurface};

const TOOLBAR_HEIGHT: u32 = 72;
const TOOLBAR_COLOR: flatland::ColorRgba =
    flatland::ColorRgba { red: 0.055, green: 0.071, blue: 0.102, alpha: 1.0 };
const ACCENT_COLOR: flatland::ColorRgba =
    flatland::ColorRgba { red: 0.0, green: 0.78, blue: 0.92, alpha: 1.0 };
const MUTED_COLOR: flatland::ColorRgba =
    flatland::ColorRgba { red: 0.16, green: 0.19, blue: 0.24, alpha: 1.0 };
const ADDRESS_COLOR: flatland::ColorRgba =
    flatland::ColorRgba { red: 0.11, green: 0.13, blue: 0.17, alpha: 1.0 };
const ACTIVE_CONTROL_COLOR: flatland::ColorRgba =
    flatland::ColorRgba { red: 0.0, green: 1.0, blue: 0.0, alpha: 1.0 };
const FOCUSED_ADDRESS_COLOR: flatland::ColorRgba =
    flatland::ColorRgba { red: 0.0, green: 0.0, blue: 1.0, alpha: 1.0 };
const GLYPH_COLOR: flatland::ColorRgba =
    flatland::ColorRgba { red: 1.0, green: 1.0, blue: 1.0, alpha: 1.0 };
const SECOND_TAB_URL: &str = "http://localhost:81/static.html";

fn install_navigation_listener(frame: &web::FrameProxy) -> Result<(), Error> {
    let (listener_client, mut listener_stream) =
        create_request_stream::<web::NavigationEventListenerMarker>();
    frame.r#set_navigation_event_listener(Some(listener_client))?;
    fasync::Task::local(async move {
        let result = async {
            while let Some(request) = listener_stream.try_next().await? {
                match request {
                    web::NavigationEventListenerRequest::OnNavigationStateChanged {
                        change,
                        responder,
                    } => {
                        info!(
                            "WebEngine navigation state: url={:?} title={:?} page_type={:?}                              loaded={:?} error={:?}",
                            change.url,
                            change.title,
                            change.page_type,
                            change.is_main_document_loaded,
                            change.error_detail,
                        );
                        responder.send()?;
                    }
                }
            }
            Ok::<(), Error>(())
        }
        .await;
        if let Err(error) = result {
            warn!("WebEngine navigation listener stopped: {error:#}");
        }
    })
    .detach();
    Ok(())
}

#[derive(Clone)]
struct BrowserFrame {
    frame: web::FrameProxy,
    navigation: web::NavigationControllerProxy,
}

impl BrowserFrame {
    async fn new(context: &web::ContextProxy, url: &str) -> Result<Self, Error> {
        let (frame, frame_server) = create_proxy::<web::FrameMarker>();
        context.r#create_frame(frame_server)?;
        let (navigation, navigation_server) = create_proxy::<web::NavigationControllerMarker>();
        frame.r#get_navigation_controller(navigation_server)?;
        install_navigation_listener(&frame)?;
        navigation
            .r#load_url(url, web::LoadUrlParams::default())
            .await?
            .map_err(|error| anyhow!("load URL failed: {error:?}"))?;
        info!("WebEngine navigation accepted: {url}");
        Ok(Self { frame, navigation })
    }
}

struct Browser {
    _context_provider: web::ContextProviderProxy,
    context: web::ContextProxy,
    initial_frame: BrowserFrame,
}

impl Browser {
    async fn new(url: &str) -> Result<Self, Error> {
        let context_provider = connect_to_protocol::<web::ContextProviderMarker>()
            .context("connect to WebEngine ContextProvider")?;
        let svc = fuchsia_fs::directory::open_in_namespace("/svc", fio::Flags::empty())
            .context("clone component service directory")?;
        let service_directory = ClientEnd::<fio::DirectoryMarker>::new(
            svc.into_channel().map_err(|_| anyhow!("convert /svc proxy to channel"))?.into_zx_channel(),
        );

        let (context, context_server) = create_proxy::<web::ContextMarker>();
        context_provider.r#create(
            web::CreateContextParams {
                service_directory: Some(service_directory),
                features: Some(web::ContextFeatureFlags::NETWORK),
                ..Default::default()
            },
            context_server,
        )?;

        let initial_frame = BrowserFrame::new(&context, url).await?;
        Ok(Self { _context_provider: context_provider, context, initial_frame })
    }
}

struct BrowserTab {
    frame: BrowserFrame,
    viewport_transform_value: u64,
    child_watcher: flatland::ChildViewWatcherProxy,
    view_ref: Option<views::ViewRef>,
    url: String,
}

impl BrowserTab {
    async fn wait_until_presented(&mut self) -> Result<(), Error> {
        if self.view_ref.is_none() {
            self.view_ref = Some(self.child_watcher.r#get_view_ref().await?);
        }
        let status = self.child_watcher.r#get_status().await?;
        if status != flatland::ChildViewStatus::ContentHasPresented {
            return Err(anyhow!("unexpected child view status: {status:?}"));
        }
        Ok(())
    }
}

fn display_url(url: &str, width: u32) -> String {
    let max_chars = ((width / 8).max(8) as usize).min(url.len().max(8));
    if url.len() <= max_chars {
        return url.to_string();
    }
    let trimmed = url.trim_start_matches("https://").trim_start_matches("http://");
    if trimmed.len() <= max_chars {
        return trimmed.to_string();
    }
    format!("{}…", &trimmed[..max_chars.saturating_sub(1)])
}

fn create_tab_view(
    flatland: &flatland::FlatlandProxy,
    frame: BrowserFrame,
    index: usize,
    size: fmath::SizeU,
    page_height: u32,
    url: &str,
) -> Result<BrowserTab, Error> {
    let ViewCreationTokenPair { view_creation_token, viewport_creation_token } =
        ViewCreationTokenPair::new()?;
    let viewport_transform_value = 100 + (index as u64 * 2);
    let viewport_transform = flatland::TransformId { value: viewport_transform_value };
    let viewport_content = flatland::ContentId { value: viewport_transform_value + 1 };
    let (child_watcher, child_watcher_server) =
        create_proxy::<flatland::ChildViewWatcherMarker>();
    flatland.create_transform(&viewport_transform)?;
    flatland.create_viewport(
        &viewport_content,
        viewport_creation_token,
        &flatland::ViewportProperties {
            logical_size: Some(fmath::SizeU { width: size.width, height: page_height }),
            ..Default::default()
        },
        child_watcher_server,
    )?;
    flatland.set_content(&viewport_transform, &viewport_content)?;
    flatland.set_translation(
        &viewport_transform,
        &fmath::Vec_ { x: 0, y: TOOLBAR_HEIGHT as i32 },
    )?;
    frame.frame.r#create_view2(web::CreateView2Args {
        view_creation_token: Some(view_creation_token),
        ..Default::default()
    })?;
    Ok(BrowserTab {
        frame,
        viewport_transform_value,
        child_watcher,
        view_ref: None,
        url: url.to_string(),
    })
}

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

#[derive(Debug)]
enum AddressKey {
    Character(char),
    Backspace,
    Enter,
}

async fn watch_keyboard(
    mut stream: input3::KeyboardListenerRequestStream,
    sender: UnboundedSender<AddressKey>,
) {
    while let Some(request) = stream.next().await {
        let Ok(input3::KeyboardListenerRequest::OnKeyEvent { event, responder }) = request else {
            continue;
        };
        let key = if event.type_ == Some(input3::KeyEventType::Pressed) {
            match event.key_meaning {
                Some(input3::KeyMeaning::Codepoint(codepoint)) => {
                    char::from_u32(codepoint).map(AddressKey::Character)
                }
                Some(input3::KeyMeaning::NonPrintableKey(input3::NonPrintableKey::Backspace)) => {
                    Some(AddressKey::Backspace)
                }
                Some(input3::KeyMeaning::NonPrintableKey(input3::NonPrintableKey::Enter)) => {
                    Some(AddressKey::Enter)
                }
                _ => None,
            }
        } else {
            None
        };
        let status = if let Some(key) = key {
            if sender.unbounded_send(key).is_ok() {
                input3::KeyEventStatus::Handled
            } else {
                return;
            }
        } else {
            input3::KeyEventStatus::NotHandled
        };
        if responder.send(status).is_err() {
            return;
        }
    }
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
                warn!("TouchSource connection closed: {error:?}");
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
                    if let Some((_, stored_position)) = pending_interactions
                        .iter_mut()
                        .find(|(stored_interaction, _)| *stored_interaction == interaction)
                    {
                        *stored_position = Some(position);
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

async fn create_browser_view(
    root_token: views::ViewCreationToken,
    context: &web::ContextProxy,
    initial_frame: BrowserFrame,
    initial_url: &str,
) -> Result<(), Error> {
    let flatland = connect_to_protocol::<flatland::FlatlandMarker>()
        .context("connect to Flatland")?;
    let (parent_watcher, parent_watcher_server) =
        create_proxy::<flatland::ParentViewportWatcherMarker>();
    let (touch_source, touch_source_server) = create_proxy::<pointer::TouchSourceMarker>();
    let (focuser, focuser_server) = create_proxy::<views::FocuserMarker>();
    let keyboard = connect_to_protocol::<input3::KeyboardMarker>().context("connect to Keyboard")?;
    let (keyboard_client, keyboard_stream) =
        create_request_stream::<input3::KeyboardListenerMarker>();
    let view_ref_pair = fuchsia_scenic::ViewRefPair::new()?;
    let view_ref = fuchsia_scenic::duplicate_view_ref(&view_ref_pair.view_ref)?;
    let keyboard_view_ref = fuchsia_scenic::duplicate_view_ref(&view_ref_pair.view_ref)?;
    flatland.r#create_view2(
        root_token,
        views::ViewIdentityOnCreation::from(view_ref_pair),
        flatland::ViewBoundProtocols {
            view_focuser: Some(focuser_server),
            touch_source: Some(touch_source_server),
            ..Default::default()
        },
        parent_watcher_server,
    )?;

    keyboard.r#add_listener(keyboard_view_ref, keyboard_client).await?;

    let layout = parent_watcher.r#get_layout().await?;
    let size = layout.logical_size.ok_or_else(|| anyhow!("parent supplied no logical size"))?;
    let toolbar_height = TOOLBAR_HEIGHT.min(size.height.saturating_sub(1));
    let page_height = size.height.saturating_sub(toolbar_height);

    let root = flatland::TransformId { value: 1 };
    flatland.create_transform(&root)?;
    flatland.set_root_transform(&root)?;
    flatland.set_hit_regions(
        &root,
        &[flatland::HitRegion {
            region: fmath::RectF {
                x: 0.0,
                y: 0.0,
                width: size.width as f32,
                height: toolbar_height as f32,
            },
            hit_test: flatland::HitTestInteraction::Default,
        }],
    )?;

    let narrow = size.width < 520;
    create_rect(
        &flatland,
        &root,
        2,
        3,
        &TOOLBAR_COLOR,
        fmath::SizeU { width: size.width, height: toolbar_height },
        fmath::Vec_ { x: 0, y: 0 },
    )?;
    if !narrow {
    create_rect(
        &flatland,
        &root,
        4,
        5,
        &ACCENT_COLOR,
        fmath::SizeU { width: 40, height: 40 },
        fmath::Vec_ { x: 16, y: 16 },
    )?;
    create_rect(
        &flatland,
        &root,
        6,
        7,
        &MUTED_COLOR,
        fmath::SizeU { width: 40, height: 40 },
        fmath::Vec_ { x: 64, y: 16 },
    )?;
    }
    let btn = if narrow { 28 } else { 40 };
    let addr_x = if narrow { 8 } else { 116 };
    let address_width = if narrow {
        size.width.saturating_sub(16).max(48)
    } else {
        size.width.saturating_sub(180).max(1)
    };
    create_rect(
        &flatland,
        &root,
        8,
        9,
        &ADDRESS_COLOR,
        fmath::SizeU { width: address_width, height: if narrow { 28 } else { 40 } },
        fmath::Vec_ { x: addr_x, y: if narrow { 36 } else { 16 } },
    )?;
    create_rect(
        &flatland,
        &root,
        10,
        11,
        &ACCENT_COLOR,
        fmath::SizeU { width: 40, height: 40 },
        fmath::Vec_ { x: size.width.saturating_sub(56) as i32, y: 16 },
    )?;

    create_rect(
        &flatland,
        &root,
        52,
        53,
        &ACCENT_COLOR,
        fmath::SizeU { width: 40, height: 14 },
        fmath::Vec_ { x: size.width.saturating_sub(56) as i32, y: 1 },
    )?;
    create_rect(
        &flatland,
        &root,
        82,
        83,
        &GLYPH_COLOR,
        fmath::SizeU { width: 16, height: 2 },
        fmath::Vec_ { x: size.width.saturating_sub(44) as i32, y: 7 },
    )?;
    create_rect(
        &flatland,
        &root,
        84,
        85,
        &GLYPH_COLOR,
        fmath::SizeU { width: 2, height: 12 },
        fmath::Vec_ { x: size.width.saturating_sub(37) as i32, y: 2 },
    )?;
    create_rect(
        &flatland,
        &root,
        54,
        55,
        &MUTED_COLOR,
        fmath::SizeU { width: 104, height: 14 },
        fmath::Vec_ { x: 116, y: 1 },
    )?;
    create_rect(
        &flatland,
        &root,
        56,
        57,
        &TOOLBAR_COLOR,
        fmath::SizeU { width: 104, height: 14 },
        fmath::Vec_ { x: 220, y: 1 },
    )?;

    let shown_url = display_url(initial_url, address_width);
    let mut address_text_surface = TextSurface::new(
        &flatland,
        &root,
        flatland::TransformId { value: 14 },
        flatland::ContentId { value: 15 },
        fmath::SizeU { width: address_width, height: if narrow { 28 } else { 40 } },
        fmath::Vec_ { x: addr_x, y: if narrow { 36 } else { 16 } },
        &shown_url,
    )
    .await?;

    let _tab_one_text_surface = TextSurface::new_with_style(
        &flatland,
        &root,
        flatland::TransformId { value: 60 },
        flatland::ContentId { value: 61 },
        fmath::SizeU { width: if narrow { address_width.min(160) } else { 104 }, height: 16 },
        fmath::Vec_ { x: if narrow { 8 } else { 116 }, y: if narrow { 8 } else { 1 } },
        if narrow { "Browser" } else { "Tab 1" },
        TextStyle::TAB,
    )
    .await?;
    let mut tab_two_text_surface = None;

    let initial_tab =
        create_tab_view(&flatland, initial_frame, 0, size, page_height, initial_url)?;
    flatland.add_child(
        &root,
        &flatland::TransformId { value: initial_tab.viewport_transform_value },
    )?;
    let mut tabs = vec![initial_tab];
    let mut active_tab = 0usize;
    flatland.present(flatland::PresentArgs::default())?;
    tabs[active_tab].wait_until_presented().await?;
    info!("Presented native Rust browser chrome at {}x{}", size.width, size.height);

    let (touch_sender, touch_events) = unbounded();
    fasync::Task::local(watch_touch_source(touch_source, touch_sender)).detach();
    let (key_sender, key_events) = unbounded();
    fasync::Task::local(watch_keyboard(keyboard_stream, key_sender)).detach();
    let mut touch_events = touch_events.fuse();
    let mut key_events = key_events.fuse();
    let mut flatland_events = flatland.take_event_stream().fuse();
    let mut address_focused = false;
    let mut address = String::new();
    loop {
        futures::select! {
            position = touch_events.next() => {
                let Some([x, y]) = position else { break };
                if y < 16.0 &&
                    ((size.width.saturating_sub(56) as f32)..(size.width.saturating_sub(16) as f32))
                        .contains(&x)
                {
                    if tabs.len() == 1 {
                        let frame = BrowserFrame::new(context, SECOND_TAB_URL).await?;
                        tabs.push(create_tab_view(
                            &flatland,
                            frame,
                            1,
                            size,
                            page_height,
                            SECOND_TAB_URL,
                        )?);
                        tab_two_text_surface = Some(
                            TextSurface::new_with_style(
                                &flatland,
                                &root,
                                flatland::TransformId { value: 70 },
                                flatland::ContentId { value: 71 },
                                fmath::SizeU { width: 104, height: 14 },
                                fmath::Vec_ { x: 220, y: 1 },
                                "Tab 2",
                                TextStyle::TAB,
                            )
                            .await?,
                        );
                        flatland.set_solid_fill(
                            &flatland::ContentId { value: 57 },
                            &MUTED_COLOR,
                            &fmath::SizeU { width: 104, height: 14 },
                        )?;
                    }
                    if active_tab != 1 {
                        flatland.remove_child(
                            &root,
                            &flatland::TransformId {
                                value: tabs[active_tab].viewport_transform_value,
                            },
                        )?;
                        flatland.add_child(
                            &root,
                            &flatland::TransformId { value: tabs[1].viewport_transform_value },
                        )?;
                        active_tab = 1;
                        address_text_surface.update(&flatland, &tabs[active_tab].url).await?;
                        tabs[active_tab].wait_until_presented().await?;
                        debug_assert!(tab_two_text_surface.is_some());
                        info!("Activated native browser tab 2");
                    }
                } else if y < 16.0 && (116.0..220.0).contains(&x) && active_tab != 0 {
                    flatland.remove_child(
                        &root,
                        &flatland::TransformId {
                            value: tabs[active_tab].viewport_transform_value,
                        },
                    )?;
                    flatland.add_child(
                        &root,
                        &flatland::TransformId { value: tabs[0].viewport_transform_value },
                    )?;
                    active_tab = 0;
                    address_text_surface.update(&flatland, &tabs[active_tab].url).await?;
                    info!("Activated native browser tab 1");
                } else if y < 16.0 && (220.0..324.0).contains(&x) && tabs.len() > 1 && active_tab != 1 {
                    flatland.remove_child(
                        &root,
                        &flatland::TransformId {
                            value: tabs[active_tab].viewport_transform_value,
                        },
                    )?;
                    flatland.add_child(
                        &root,
                        &flatland::TransformId { value: tabs[1].viewport_transform_value },
                    )?;
                    active_tab = 1;
                    address_text_surface.update(&flatland, &tabs[active_tab].url).await?;
                    info!("Activated native browser tab 2");
                } else if (16.0..56.0).contains(&x) && (16.0..56.0).contains(&y) {
                    tabs[active_tab].frame.navigation.r#go_back()?;
                    flatland.set_solid_fill(
                        &flatland::ContentId { value: 5 },
                        &ACTIVE_CONTROL_COLOR,
                        &fmath::SizeU { width: 40, height: 40 },
                    )?;
                    flatland.set_solid_fill(
                        &flatland::ContentId { value: 7 },
                        &MUTED_COLOR,
                        &fmath::SizeU { width: 40, height: 40 },
                    )?;
                    flatland.present(flatland::PresentArgs::default())?;
                    info!("Navigated WebEngine back from native browser control at ({x}, {y})");
                } else if (64.0..104.0).contains(&x) && (16.0..56.0).contains(&y) {
                    tabs[active_tab].frame.navigation.r#go_forward()?;
                    flatland.set_solid_fill(
                        &flatland::ContentId { value: 5 },
                        &ACCENT_COLOR,
                        &fmath::SizeU { width: 40, height: 40 },
                    )?;
                    flatland.set_solid_fill(
                        &flatland::ContentId { value: 7 },
                        &ACTIVE_CONTROL_COLOR,
                        &fmath::SizeU { width: 40, height: 40 },
                    )?;
                    flatland.present(flatland::PresentArgs::default())?;
                    info!("Navigated WebEngine forward from native browser control at ({x}, {y})");
                } else if (116.0..(size.width.saturating_sub(64) as f32)).contains(&x)
                    && (16.0..56.0).contains(&y)
                {
                    let focus_target = fuchsia_scenic::duplicate_view_ref(&view_ref)?;
                    focuser
                        .request_focus(focus_target)
                        .await?
                        .map_err(|error| anyhow!("request browser focus: {error:?}"))?;
                    flatland.set_solid_fill(
                        &flatland::ContentId { value: 9 },
                        &FOCUSED_ADDRESS_COLOR,
                        &fmath::SizeU { width: address_width, height: 40 },
                    )?;
                    flatland.present(flatland::PresentArgs::default())?;
                    address_focused = true;
                    address.clear();
                    info!("Focused native browser address field at ({x}, {y})");
                } else if ((size.width.saturating_sub(56) as f32)..(size.width.saturating_sub(16) as f32))
                    .contains(&x)
                    && (16.0..56.0).contains(&y)
                {
                    tabs[active_tab].frame.navigation.r#reload(web::ReloadType::NoCache)?;
                    flatland.set_solid_fill(
                        &flatland::ContentId { value: 11 },
                        &ACTIVE_CONTROL_COLOR,
                        &fmath::SizeU { width: 40, height: 40 },
                    )?;
                    flatland.present(flatland::PresentArgs::default())?;
                    info!("Reloaded WebEngine from native browser control at ({x}, {y})");
                }
            }
            key = key_events.next() => {
                let Some(key) = key else { break };
                if !address_focused {
                    continue;
                }
                match key {
                    AddressKey::Character(character) if !character.is_control() => {
                        address.push(character);
                        address_text_surface.update(&flatland, &address).await?;
                    }
                    AddressKey::Backspace => {
                        address.pop();
                        address_text_surface.update(&flatland, &address).await?;
                    }
                    AddressKey::Enter if !address.is_empty() => {
                        tabs[active_tab]
                            .frame
                            .navigation
                            .r#load_url(&address, web::LoadUrlParams::default())
                            .await?
                            .map_err(|error| anyhow!("load typed URL: {error:?}"))?;
                        flatland.set_solid_fill(
                            &flatland::ContentId { value: 9 },
                            &ADDRESS_COLOR,
                            &fmath::SizeU { width: address_width, height: 40 },
                        )?;
                        flatland.present(flatland::PresentArgs::default())?;
                        tabs[active_tab].url = address.clone();
                        address_focused = false;
                        address.clear();
                        info!("Loaded URL from native browser address field");
                    }
                    _ => {}
                }
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
    Ok(())
}

async fn serve_view_provider(
    mut stream: ViewProviderRequestStream,
    context: web::ContextProxy,
    initial_frame: BrowserFrame,
    initial_url: String,
) -> Result<(), Error> {
    while let Some(request) = stream.try_next().await? {
        match request {
            ViewProviderRequest::CreateView2 { args, .. } => {
                let token = args
                    .view_creation_token
                    .ok_or_else(|| anyhow!("CreateView2 omitted view_creation_token"))?;
                create_browser_view(
                    token,
                    &context,
                    initial_frame.clone(),
                    &initial_url,
                )
                .await?;
            }
            other => warn!("Unsupported ViewProvider request: {other:?}"),
        }
    }
    Ok(())
}

#[fuchsia::main(logging = true)]
async fn main() -> Result<(), Error> {
    let config = Config::take_from_startup_handle();
    if config.use_vulkan {
        warn!("Ignoring use_vulkan=true; browser uses WebEngine SwiftShader on FEMU");
    }
    let initial_url = config.html.clone();
    let browser = Browser::new(&initial_url).await?;

    let mut fs = ServiceFs::new_local();
    fs.dir("svc").add_fidl_service(|stream: ViewProviderRequestStream| stream);
    fs.take_and_serve_directory_handle().context("serve ViewProvider")?;
    while let Some(stream) = fs.next().await {
        serve_view_provider(
            stream,
            browser.context.clone(),
            browser.initial_frame.clone(),
            initial_url.clone(),
        )
        .await?;
    }
    Ok(())
}
