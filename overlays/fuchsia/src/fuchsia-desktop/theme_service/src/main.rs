use anyhow::Error;
use fuchsia_component::server::ServiceFs;
use futures::StreamExt;
use std::sync::Arc;
use theme_service_core::{Authority, Diagnostics, serve_native_theme};

const PACKAGES: [&[u8]; 4] = [
    include_bytes!("../../theme_catalog/catalog/instrument-studio-base16.package.json"),
    include_bytes!("../../theme_catalog/catalog/instrument-studio-base24.package.json"),
    include_bytes!("../../theme_catalog/catalog/instrument-studio-dtcg.package.json"),
    include_bytes!("../../theme_catalog/catalog/instrument-studio-omarchy.package.json"),
];

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
                let _ = serve_native_theme(authority, stream).await;
            })
            .detach();
        }
    });
    fs.take_and_serve_directory_handle()?;
    fs.collect::<()>().await;
    Ok(())
}
