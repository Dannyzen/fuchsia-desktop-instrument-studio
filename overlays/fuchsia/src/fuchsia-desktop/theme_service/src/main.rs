use anyhow::Error;
use theme_service_core::{Authority, ConnectionWatch, Diagnostics, WatchAction, to_fidl};
use fidl::endpoints::RequestStream;
use fidl_fuchsia_instrumentstudio_theme::{NativeThemeRequest, NativeThemeRequestStream};
use fuchsia_component::server::ServiceFs;
use futures::{StreamExt, TryStreamExt};
use std::sync::Arc;
use zx::Status;

const PACKAGES: [&[u8]; 4] = [
    include_bytes!("../../theme_catalog/catalog/instrument-studio-base16.package.json"),
    include_bytes!("../../theme_catalog/catalog/instrument-studio-base24.package.json"),
    include_bytes!("../../theme_catalog/catalog/instrument-studio-dtcg.package.json"),
    include_bytes!("../../theme_catalog/catalog/instrument-studio-omarchy.package.json"),
];

async fn serve(
    authority: Arc<Authority>,
    mut stream: NativeThemeRequestStream,
) -> Result<(), fidl::Error> {
    // One parked responder per connection is the hanging-get invariant. Separate
    // ServiceFs connections therefore park independently without reader coupling.
    let mut watch_state = ConnectionWatch::default();
    while let Some(request) = stream.try_next().await? {
        match request {
            NativeThemeRequest::ListThemes { responder } => {
                responder.send(
                    &authority
                        .themes()
                        .map(to_fidl)
                        .map(|s| s.metadata)
                        .collect::<Vec<_>>(),
                )?;
            }
            NativeThemeRequest::GetTheme { id, responder } => {
                let metadata = authority
                    .themes()
                    .find(|s| s.id == id)
                    .map(|s| to_fidl(s).metadata);
                let result = metadata.as_ref().ok_or_else(|| Status::NOT_FOUND.into_raw());
                responder.send(result)?;
            }
            NativeThemeRequest::GetCurrent { responder } => {
                responder.send(&to_fidl(&authority.current()))?
            }
            NativeThemeRequest::WatchCurrent {
                observed_generation,
                responder,
            } => {
                // P3-S1 is immutable: equality remains pending until disconnect. Any unequal
                // process-scoped generation replies, including a pre-restart higher value.
                let current = authority.current();
                match watch_state.observe(observed_generation, current.generation, responder) {
                    WatchAction::Reply(responder) => responder.send(&to_fidl(&current))?,
                    WatchAction::Parked => {}
                    WatchAction::BadState => {
                        stream.control_handle()
                            .shutdown_with_epitaph(Status::BAD_STATE);
                        return Ok(());
                    }
                }
            }
        }
    }
    Ok(())
}

#[fuchsia::main]
async fn main() -> Result<(), Error> {
    let authority = Arc::new(Authority::from_packaged(PACKAGES));
    let _diagnostics =
        Diagnostics::record(fuchsia_inspect::component::inspector().root(), &authority);
    let mut fs = ServiceFs::new_local();
    fs.dir("svc").add_fidl_service({
        let authority = authority.clone();
        move |stream| {
            let authority = authority.clone();
            fuchsia_async::Task::local(async move {
                let _ = serve(authority, stream).await;
            })
            .detach();
        }
    });
    fs.take_and_serve_directory_handle()?;
    fs.collect::<()>().await;
    Ok(())
}
