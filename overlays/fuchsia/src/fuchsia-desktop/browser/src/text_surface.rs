// Copyright 2026 The Fuchsia Desktop Authors.
// Use of this source code is governed by a BSD-style license.

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
use fuchsia_async::OnSignals;
use fuchsia_component::client::connect_to_protocol;
use fuchsia_framebuffer::FrameUsage;
use fuchsia_framebuffer::sysmem::BufferCollectionAllocator;
use fuchsia_scenic::{BufferCollectionTokenPair, duplicate_buffer_collection_import_token};
use zx::{Event, Signals};

const FONT_DATA: &[u8] = include_bytes!(
    "../../../../prebuilt/third_party/fonts/robotoslab/RobotoSlab-Regular.ttf"
);
const BUFFER_COUNT: usize = 2;

#[derive(Clone, Copy)]
pub struct TextStyle {
    pub font_size: f32,
    pub left_padding: i32,
    pub top_padding: i32,
}

impl TextStyle {
    pub const ADDRESS: Self = Self { font_size: 20.0, left_padding: 12, top_padding: 8 };
    pub const TAB: Self = Self { font_size: 12.0, left_padding: 6, top_padding: 0 };
}

pub struct TextSurface {
    context: Context,
    face: FontFace,
    glyphs: GlyphMap,
    size: fmath::SizeU,
    transform_value: u64,
    content_base: u64,
    current_index: usize,
    style: TextStyle,
}

impl TextSurface {
    pub async fn new(
        flatland: &flatland::FlatlandProxy,
        parent: &flatland::TransformId,
        transform_id: flatland::TransformId,
        content_id: flatland::ContentId,
        size: fmath::SizeU,
        translation: fmath::Vec_,
        text: &str,
    ) -> Result<Self, Error> {
        Self::new_with_style(
            flatland,
            parent,
            transform_id,
            content_id,
            size,
            translation,
            text,
            TextStyle::ADDRESS,
        )
        .await
    }

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
            BUFFER_COUNT,
        )?;
        buffer_allocator.set_name(100, "FuchsiaBrowserAddressText")?;

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
            .map_err(|error| anyhow::anyhow!("register text buffer collection: {error:?}"))?;
        buffer_allocator
            .allocate_buffers(true)
            .await
            .context("allocate address text buffers")?;

        for index in 0..BUFFER_COUNT {
            let image_id = flatland::ContentId { value: content_id.value + index as u64 };
            let import_token =
                duplicate_buffer_collection_import_token(&buffer_tokens.import_token)?;
            flatland.create_image(
                &image_id,
                import_token,
                index as u32,
                &flatland::ImageProperties { size: Some(size), ..Default::default() },
            )?;
            flatland.set_image_destination_size(&image_id, &size)?;
            flatland.set_image_blending_function(&image_id, flatland::BlendMode::SrcOver)?;
            context.get_image(index as u32);
        }

        flatland.create_transform(&transform_id)?;
        flatland.set_content(&transform_id, &content_id)?;
        flatland.set_translation(&transform_id, &translation)?;
        flatland.add_child(parent, &transform_id)?;

        let mut surface = Self {
            context,
            face: FontFace::new(FONT_DATA)?,
            glyphs: GlyphMap::new(),
            size,
            transform_value: transform_id.value,
            content_base: content_id.value,
            current_index: 0,
            style,
        };
        surface.render_into(0, text)?;
        Ok(surface)
    }

    pub async fn update(
        &mut self,
        flatland: &flatland::FlatlandProxy,
        text: &str,
    ) -> Result<(), Error> {
        let next_index = (self.current_index + 1) % BUFFER_COUNT;
        self.render_into(next_index, text)?;
        flatland.set_content(
            &flatland::TransformId { value: self.transform_value },
            &flatland::ContentId { value: self.content_base + next_index as u64 },
        )?;

        let release_event = Event::create();
        let local_release_event = release_event.duplicate_handle(zx::Rights::SAME_RIGHTS)?;
        flatland.present(flatland::PresentArgs {
            release_fences: Some(vec![release_event]),
            ..Default::default()
        })?;
        OnSignals::new(&local_release_event, Signals::EVENT_SIGNALED).await?;
        self.current_index = next_index;
        Ok(())
    }

    fn render_into(&mut self, index: usize, text: &str) -> Result<(), Error> {
        let text = Text::new(
            &mut self.context,
            text,
            self.style.font_size,
            self.size
                .width
                .saturating_sub((self.style.left_padding * 2) as u32) as f32,
            &self.face,
            &mut self.glyphs,
        );
        let mut composition = Composition::new(Color { r: 0, g: 0, b: 0, a: 0 });
        composition.insert(
            Order::new(0)?,
            Layer {
                raster: text
                    .raster
                    .translate(vec2(self.style.left_padding, self.style.top_padding)),
                clip: None,
                style: Style {
                    fill_rule: FillRule::NonZero,
                    fill: Fill::Solid(Color { r: 255, g: 255, b: 255, a: 255 }),
                    blend_mode: BlendMode::Over,
                },
            },
        );
        let image = self.context.get_image(index as u32);
        self.context.render(
            &mut composition,
            None,
            image,
            &RenderExt {
                pre_clear: Some(PreClear { color: Color { r: 0, g: 0, b: 0, a: 0 } }),
                ..Default::default()
            },
        );
        Ok(())
    }
}
