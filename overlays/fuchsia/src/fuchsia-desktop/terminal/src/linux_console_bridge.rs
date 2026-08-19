// Copyright 2026 The Fuchsia Desktop Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

//! Bridge Workbench terminal PTY stdio to Alpine/Linux via Starnix SpawnConsole.

use anyhow::{Context as _, Error, bail};
use fidl_fuchsia_starnix_container as fstarcontainer;
use fuchsia_async as fasync;
use fuchsia_component::client::connect_to_protocol;
use futures::{AsyncReadExt, AsyncWriteExt};
use std::env;
use std::io::{Read as _, Write as _};
use std::os::fd::FromRawFd;
use zx;

fn forward_stdin_to_socket(local_tx: zx::Socket) {
    std::thread::spawn(move || {
        let mut executor = fasync::LocalExecutor::default();
        executor.run_singlethreaded(async move {
            let mut tx = fasync::Socket::from_socket(local_tx);
            let mut stdin = unsafe { std::fs::File::from_raw_fd(libc::dup(0)) };
            let mut buf = [0u8; 4096];
            loop {
                let n = match stdin.read(&mut buf) {
                    Ok(0) | Err(_) => break,
                    Ok(n) => n,
                };
                if tx.write_all(&buf[..n]).await.is_err() {
                    break;
                }
            }
        });
    });
}

async fn forward_socket_to_stdout(local_rx: zx::Socket) {
    let mut rx = fasync::Socket::from_socket(local_rx);
    fasync::unblock(move || {
        let mut executor = fasync::LocalExecutor::default();
        executor.run_singlethreaded(async move {
            let mut stdout = unsafe { std::fs::File::from_raw_fd(libc::dup(1)) };
            let mut buf = [0u8; 4096];
            loop {
                match rx.read(&mut buf).await {
                    Ok(0) | Err(_) => break,
                    Ok(n) => {
                        if stdout.write_all(&buf[..n]).is_err() {
                            break;
                        }
                        let _ = stdout.flush();
                    }
                }
            }
        });
    })
    .await;
}

#[fuchsia::main(logging = true)]
async fn main() -> Result<(), Error> {
    let mut argv: Vec<String> = env::args().skip(1).collect();
    if argv.is_empty() {
        argv = vec!["/bin/bash".into(), "-l".into()];
    }
    let binary_path = argv[0].clone();

    let controller = connect_to_protocol::<fstarcontainer::ControllerMarker>().context(
        "connect fuchsia.starnix.container.Controller (linux_container must be routed)",
    )?;

    let (local_in, remote_in) = zx::Socket::create_stream();
    let (local_out, remote_out) = zx::Socket::create_stream();

    forward_stdin_to_socket(local_in);
    let stdout_task = fasync::Task::local(forward_socket_to_stdout(local_out));

    let spawn_fut = controller.spawn_console(fstarcontainer::ControllerSpawnConsoleRequest {
        console_in: Some(remote_in),
        console_out: Some(remote_out),
        binary_path: Some(binary_path),
        argv: Some(argv),
        environ: Some(vec![
            "TERM=xterm-256color".into(),
            "HOME=/root".into(),
            "USER=root".into(),
            "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin".into(),
        ]),
        window_size: Some(fstarcontainer::ConsoleWindowSize {
            rows: 24,
            cols: 80,
            x_pixels: 0,
            y_pixels: 0,
        }),
        ..Default::default()
    });

    let (spawn_res, _) = futures::join!(spawn_fut, stdout_task);
    match spawn_res.context("SpawnConsole FIDL")? {
        Ok(code) => std::process::exit(i32::from(code)),
        Err(err) => {
            eprintln!("Workbench Linux console failed: {err:?}");
            bail!("SpawnConsole failed: {err:?}");
        }
    }
}
