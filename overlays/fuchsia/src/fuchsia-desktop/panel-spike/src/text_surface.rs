// Copyright 2026 The Fuchsia Desktop Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

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
use fuchsia_scenic::{BufferCollectionTokenPair, duplicate_buffer_collection_import_token};

const FONT_DATA: &[u8] = include_bytes!(
    "../../../../prebuilt/third_party/fonts/robotoslab/RobotoSlab-Regular.ttf"
);

#[derive(Clone, Copy)]
pub struct TextStyle {
    pub font_size: f32,
    pub left_padding: i32,
    pub top_padding: i32,
}

pub struct TextSurface {
    _context: Context,
    _face: FontFace,
    _glyphs: GlyphMap,
}

impl TextSurface {
    #[allow(clippy::too_many_arguments)]
    pub async fn new_with_style(
        flatland: &flatland::FlatlandProxy,
        parent: &flatland::TransformId,
        transform_id: flatland::TransformId,
        content_id: flatland::ContentId,
        size: fmath::SizeU,
        translation: fmath::Vec_,
        text: &str,
        style: TextStyle,
    ) -> Result<Self, Error> {
        let mut buffer_allocator = BufferCollectionAllocator::new(
            size.width,
            size.height,
            images2::PixelFormat::B8G8R8A8,
            FrameUsage::Cpu,
            1,
        )?;
        buffer_allocator.set_name(100, "FuchsiaCosmicPanelText")?;

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
            .context("connect to Flatland Allocator")?;
        allocator
            .register_buffer_collection(flatland::RegisterBufferCollectionArgs {
                export_token: Some(buffer_tokens.export_token),
                buffer_collection_token2: Some(scenic_token),
                ..Default::default()
            })
            .await?
            .map_err(|error| anyhow::anyhow!("register panel text buffer collection: {error:?}"))?;
        buffer_allocator.allocate_buffers(true).await.context("allocate panel text buffer")?;

        let import_token = duplicate_buffer_collection_import_token(&buffer_tokens.import_token)?;
        flatland.create_image(
            &content_id,
            import_token,
            0,
            &flatland::ImageProperties { size: Some(size), ..Default::default() },
        )?;
        flatland.set_image_destination_size(&content_id, &size)?;
        flatland.set_image_blending_function(&content_id, flatland::BlendMode::SrcOver)?;
        context.get_image(0);
        flatland.create_transform(&transform_id)?;
        flatland.set_content(&transform_id, &content_id)?;
        flatland.set_translation(&transform_id, &translation)?;
        flatland.add_child(parent, &transform_id)?;

        let face = FontFace::new(FONT_DATA)?;
        let mut glyphs = GlyphMap::new();
        let text = Text::new(
            &mut context,
            text,
            style.font_size,
            size.width.saturating_sub((style.left_padding * 2) as u32) as f32,
            &face,
            &mut glyphs,
        );
        let mut composition = Composition::new(Color { r: 0, g: 0, b: 0, a: 0 });
        composition.insert(
            Order::new(0)?,
            Layer {
                raster: text.raster.translate(vec2(style.left_padding, style.top_padding)),
                clip: None,
                style: Style {
                    fill_rule: FillRule::NonZero,
                    fill: Fill::Solid(Color { r: 255, g: 255, b: 255, a: 255 }),
                    blend_mode: BlendMode::Over,
                },
            },
        );
        let image = context.get_image(0);
        context.render(
            &mut composition,
            None,
            image,
            &RenderExt {
                pre_clear: Some(PreClear { color: Color { r: 0, g: 0, b: 0, a: 0 } }),
                ..Default::default()
            },
        );
        Ok(Self { _context: context, _face: face, _glyphs: glyphs })
    }
}
