use anyhow::Error;
use fidl_fuchsia_instrumentstudio_theme as ftheme;
use fuchsia_component::server::ServiceFs;
use futures::StreamExt;
use std::sync::Arc;
use theme_service_core::{
    Authority, Diagnostics, SettingsControl, serve_native_theme, serve_native_theme_settings,
};

const PACKAGES: [&[u8]; 4] = [
    include_bytes!("../../theme_catalog/catalog/instrument-studio-base16.package.json"),
    include_bytes!("../../theme_catalog/catalog/instrument-studio-base24.package.json"),
    include_bytes!("../../theme_catalog/catalog/instrument-studio-dtcg.package.json"),
    include_bytes!("../../theme_catalog/catalog/instrument-studio-omarchy.package.json"),
];
const STATE_PATH: &str = "/data/native-theme-state.v1";

enum IncomingService {
    NativeTheme(ftheme::NativeThemeRequestStream),
    Settings(ftheme::NativeThemeSettingsRequestStream),
}

#[fuchsia::main(logging = true)]
async fn main() -> Result<(), Error> {
    let startup = std::time::Instant::now();
    let state = std::fs::read(STATE_PATH).ok();
    let authority = Arc::new(Authority::from_packaged_and_state(
        PACKAGES,
        state.as_deref(),
    ));
    let diagnostics = Arc::new(Diagnostics::record(
        fuchsia_inspect::component::inspector().root(),
        &authority,
        state.as_deref(),
    ));
    let control = Arc::new(SettingsControl::new(
        authority.clone(),
        STATE_PATH,
        diagnostics.clone(),
    ));
    control.record_active_as_last_known_good();
    let mut fs = ServiceFs::new_local();
    fs.dir("svc")
        .add_fidl_service(IncomingService::NativeTheme)
        .add_fidl_service(IncomingService::Settings);
    fs.take_and_serve_directory_handle()?;
    let elapsed_micros = u64::try_from(startup.elapsed().as_micros()).unwrap_or(u64::MAX);
    diagnostics.record_shell_survival(elapsed_micros);
    fs.for_each_concurrent(None, move |service| {
        let authority = authority.clone();
        let control = control.clone();
        let diagnostics = diagnostics.clone();
        async move {
            match service {
                IncomingService::NativeTheme(stream) => {
                    // P3-S1 shape: serve_native_theme(authority, stream), now observed.
                    let _ = serve_native_theme(authority, diagnostics, stream).await;
                }
                IncomingService::Settings(stream) => {
                    let _ = serve_native_theme_settings(control, stream).await;
                }
            }
        }
    })
    .await;
    Ok(())
}
