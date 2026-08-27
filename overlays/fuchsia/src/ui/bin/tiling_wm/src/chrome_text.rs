// Copyright 2026 The Fuchsia Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

//! Font-rendered Instrument Studio shell chrome.
//!
//! Roboto carries readable words. Material Icons carries compact semantic
//! glyphs. Both are packaged Fuchsia font assets and rasterized into one
//! transparent Flatland image per chrome region.

use anyhow::{Context as _, Error};
use carnelian::color::Color;
use carnelian::drawing::{DisplayRotation, FontFace, GlyphMap, Text};
use carnelian::render::generic::{self, Backend as _};
use carnelian::render::{
    BlendMode, Composition, Context, ContextInner, Fill, FillRule, Layer, Order, PreClear,
    RenderExt, Style,
};
use euclid::{size2, vec2};
use fidl_fuchsia_images2 as images2;
use fidl_fuchsia_math as fmath;
use fidl_fuchsia_ui_composition as flatland;
use fuchsia_component::client::connect_to_protocol;
use fuchsia_framebuffer::FrameUsage;
use fuchsia_framebuffer::sysmem::BufferCollectionAllocator;
use fuchsia_scenic::flatland::IdGenerator;
use fuchsia_scenic::{BufferCollectionTokenPair, duplicate_buffer_collection_import_token};

const ROBOTO_DATA: &[u8] =
    include_bytes!("../../../../../prebuilt/third_party/fonts/roboto/Roboto-Regular.ttf");
const MATERIAL_ICONS_DATA: &[u8] =
    include_bytes!("../../../../../prebuilt/third_party/fonts/material/MaterialIcons-Regular.ttf");

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ChromeFont {
    Text,
    Icon,
}

#[derive(Clone, Copy, Debug)]
pub struct TextRun<'a> {
    pub text: &'a str,
    pub x: i32,
    pub y: i32,
    pub font_size: f32,
    pub color: [u8; 4],
    pub font: ChromeFont,
}

impl<'a> TextRun<'a> {
    pub const fn text(text: &'a str, x: i32, y: i32, font_size: f32, color: [u8; 4]) -> Self {
        Self {
            text,
            x,
            y,
            font_size,
            color,
            font: ChromeFont::Text,
        }
    }
    pub const fn icon(text: &'a str, x: i32, y: i32, font_size: f32, color: [u8; 4]) -> Self {
        Self {
            text,
            x,
            y,
            font_size,
            color,
            font: ChromeFont::Icon,
        }
    }
}

pub struct ChromeTextSurface {
    _context: Context,
    _text_face: FontFace,
    _icon_face: FontFace,
    _text_glyphs: GlyphMap,
    _icon_glyphs: GlyphMap,
}

impl ChromeTextSurface {
    pub async fn new(
        flatland: &flatland::FlatlandProxy,
        ids: &mut IdGenerator,
        parent: &flatland::TransformId,
        size: fmath::SizeU,
        translation: fmath::Vec_,
        runs: &[TextRun<'_>],
        debug_name: &str,
    ) -> Result<Self, Error> {
        let mut buffer_allocator = BufferCollectionAllocator::new(
            size.width,
            size.height,
            images2::PixelFormat::B8G8R8A8,
            FrameUsage::Cpu,
            1,
        )?;
        buffer_allocator.set_name(100, debug_name)?;
        let context_token = buffer_allocator.duplicate_token().await?;
        let mut context = Context {
            inner: ContextInner::Forma(generic::Forma::new_context(
                context_token,
                size2(size.width, size.height),
                DisplayRotation::Deg0,
            )),
        };
        let scenic_token = buffer_allocator.duplicate_token().await?;
        let buffer_tokens = BufferCollectionTokenPair::new();
        let allocator = connect_to_protocol::<flatland::AllocatorMarker>()
            .context("connect to Flatland Allocator for chrome text")?;
        allocator
            .register_buffer_collection(flatland::RegisterBufferCollectionArgs {
                export_token: Some(buffer_tokens.export_token),
                buffer_collection_token2: Some(scenic_token),
                ..Default::default()
            })
            .await?
            .map_err(|error| anyhow::anyhow!("register chrome text buffers: {error:?}"))?;
        buffer_allocator
            .allocate_buffers(true)
            .await
            .context("allocate chrome text buffers")?;
        let content_id = ids.next_content_id();
        let import_token = duplicate_buffer_collection_import_token(&buffer_tokens.import_token)?;
        flatland.create_image(
            &content_id,
            import_token,
            0,
            &flatland::ImageProperties {
                size: Some(size),
                ..Default::default()
            },
        )?;
        flatland.set_image_destination_size(&content_id, &size)?;
        flatland.set_image_blending_function(&content_id, flatland::BlendMode::SrcOver)?;
        context.get_image(0);
        let transform_id = ids.next_transform_id();
        flatland.create_transform(&transform_id)?;
        flatland.set_content(&transform_id, &content_id)?;
        flatland.set_translation(&transform_id, &translation)?;
        flatland.add_child(parent, &transform_id)?;
        let text_face = FontFace::new(ROBOTO_DATA)?;
        let icon_face = FontFace::new(MATERIAL_ICONS_DATA)?;
        let mut text_glyphs = GlyphMap::new();
        let mut icon_glyphs = GlyphMap::new();
        let mut composition = Composition::new(Color {
            r: 0,
            g: 0,
            b: 0,
            a: 0,
        });
        for (order, run) in runs.iter().enumerate() {
            let (face, glyphs) = match run.font {
                ChromeFont::Text => (&text_face, &mut text_glyphs),
                ChromeFont::Icon => (&icon_face, &mut icon_glyphs),
            };
            let max_width = size.width.saturating_sub(run.x.max(0) as u32).max(1) as f32;
            let text = Text::new(
                &mut context,
                run.text,
                run.font_size,
                max_width,
                face,
                glyphs,
            );
            composition.insert(
                Order::new(order as u32)?,
                Layer {
                    raster: text.raster.translate(vec2(run.x, run.y)),
                    clip: None,
                    style: Style {
                        fill_rule: FillRule::NonZero,
                        fill: Fill::Solid(Color {
                            r: run.color[0],
                            g: run.color[1],
                            b: run.color[2],
                            a: run.color[3],
                        }),
                        blend_mode: BlendMode::Over,
                    },
                },
            );
        }
        let image = context.get_image(0);
        context.render(
            &mut composition,
            None,
            image,
            &RenderExt {
                pre_clear: Some(PreClear {
                    color: Color {
                        r: 0,
                        g: 0,
                        b: 0,
                        a: 0,
                    },
                }),
                ..Default::default()
            },
        );
        Ok(Self {
            _context: context,
            _text_face: text_face,
            _icon_face: icon_face,
            _text_glyphs: text_glyphs,
            _icon_glyphs: icon_glyphs,
        })
    }
}
