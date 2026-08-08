//! Process-launch helpers shared by both native launch boundaries.

#[cfg(unix)]
pub(crate) fn descriptor_limit() -> Result<libc::c_int, crate::ProtocolError> {
    // SAFETY: sysconf takes one constant and returns a process limit.
    let limit = unsafe { libc::sysconf(libc::_SC_OPEN_MAX) };
    if !(3..=1_048_576).contains(&limit) {
        return Err(crate::ProtocolError::new("broker_unavailable", None));
    }
    Ok(limit as libc::c_int)
}

#[cfg(unix)]
pub(crate) unsafe fn seal_inherited_descriptors(limit: libc::c_int) -> std::io::Result<()> {
    #[cfg(target_os = "linux")]
    {
        // close_range with CLOEXEC is atomic with respect to concurrent opens in
        // the child and preserves descriptors until exec error reporting ends.
        if unsafe {
            libc::syscall(
                libc::SYS_close_range,
                3_u32,
                u32::MAX,
                libc::CLOSE_RANGE_CLOEXEC,
            )
        } == 0
        {
            return Ok(());
        }
    }

    for descriptor in 3..limit {
        let flags = unsafe { libc::fcntl(descriptor, libc::F_GETFD) };
        if flags < 0 {
            if std::io::Error::last_os_error().raw_os_error() == Some(libc::EBADF) {
                continue;
            }
            return Err(std::io::Error::last_os_error());
        }
        if flags & libc::FD_CLOEXEC == 0
            && unsafe { libc::fcntl(descriptor, libc::F_SETFD, flags | libc::FD_CLOEXEC) } < 0
        {
            return Err(std::io::Error::last_os_error());
        }
    }
    Ok(())
}

#[cfg(windows)]
pub(crate) struct WindowsSealedChild {
    process: windows_sys::Win32::Foundation::HANDLE,
}

#[cfg(windows)]
unsafe impl Send for WindowsSealedChild {}

#[cfg(windows)]
impl WindowsSealedChild {
    pub(crate) fn try_wait(&mut self) -> std::io::Result<Option<std::process::ExitStatus>> {
        use std::os::windows::process::ExitStatusExt;
        use windows_sys::Win32::Foundation::STILL_ACTIVE;
        use windows_sys::Win32::System::Threading::GetExitCodeProcess;

        let mut code = 0_u32;
        if unsafe { GetExitCodeProcess(self.process, &mut code) } == 0 {
            return Err(std::io::Error::last_os_error());
        }
        if code == STILL_ACTIVE as u32 {
            Ok(None)
        } else {
            Ok(Some(std::process::ExitStatus::from_raw(code)))
        }
    }

    pub(crate) fn kill(&mut self) -> std::io::Result<()> {
        use windows_sys::Win32::System::Threading::TerminateProcess;

        if unsafe { TerminateProcess(self.process, 1) } == 0 {
            return Err(std::io::Error::last_os_error());
        }
        Ok(())
    }

    pub(crate) fn wait(&mut self) -> std::io::Result<std::process::ExitStatus> {
        use windows_sys::Win32::Foundation::{WAIT_FAILED, WAIT_OBJECT_0};
        use windows_sys::Win32::System::Threading::{WaitForSingleObject, INFINITE};

        match unsafe { WaitForSingleObject(self.process, INFINITE) } {
            WAIT_OBJECT_0 => self
                .try_wait()?
                .ok_or_else(|| std::io::Error::other("process wait returned without exit")),
            WAIT_FAILED => Err(std::io::Error::last_os_error()),
            _ => Err(std::io::Error::other("unexpected process wait result")),
        }
    }
}

#[cfg(windows)]
impl Drop for WindowsSealedChild {
    fn drop(&mut self) {
        use windows_sys::Win32::Foundation::CloseHandle;

        if !self.process.is_null() {
            unsafe { CloseHandle(self.process) };
        }
    }
}

#[cfg(windows)]
pub(crate) fn spawn_sealed_process(
    executable: &std::path::Path,
    arguments: &[String],
    working_directory: &std::path::Path,
) -> Result<WindowsSealedChild, crate::ProtocolError> {
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::System::Threading::{
        CreateProcessW, CREATE_NO_WINDOW, CREATE_UNICODE_ENVIRONMENT, PROCESS_INFORMATION,
        STARTUPINFOW,
    };

    let application = wide_os(executable.as_os_str())?;
    let current_directory = wide_os(working_directory.as_os_str())?;
    let mut values = Vec::with_capacity(arguments.len() + 1);
    values.push(executable.as_os_str().encode_wide().collect::<Vec<_>>());
    values.extend(
        arguments
            .iter()
            .map(|argument| argument.encode_utf16().collect()),
    );
    let mut command_line = Vec::new();
    for (index, value) in values.iter().enumerate() {
        if value.contains(&0) {
            return unavailable();
        }
        if index > 0 {
            command_line.push(b' ' as u16);
        }
        append_quoted_argument(&mut command_line, value);
    }
    command_line.push(0);
    let environment = environment_block()?;
    let startup = STARTUPINFOW {
        cb: std::mem::size_of::<STARTUPINFOW>() as u32,
        ..STARTUPINFOW::default()
    };
    let mut process_info = PROCESS_INFORMATION::default();
    // No handle is needed at this boundary, so bInheritHandles is false.
    let created = unsafe {
        CreateProcessW(
            application.as_ptr(),
            command_line.as_mut_ptr(),
            std::ptr::null(),
            std::ptr::null(),
            0,
            CREATE_NO_WINDOW | CREATE_UNICODE_ENVIRONMENT,
            environment.as_ptr().cast(),
            current_directory.as_ptr(),
            &startup,
            &mut process_info,
        )
    };
    if created == 0 || process_info.hProcess.is_null() || process_info.hThread.is_null() {
        if !process_info.hProcess.is_null() {
            unsafe { windows_sys::Win32::Foundation::CloseHandle(process_info.hProcess) };
        }
        if !process_info.hThread.is_null() {
            unsafe { windows_sys::Win32::Foundation::CloseHandle(process_info.hThread) };
        }
        return unavailable();
    }
    unsafe { windows_sys::Win32::Foundation::CloseHandle(process_info.hThread) };
    Ok(WindowsSealedChild {
        process: process_info.hProcess,
    })
}

#[cfg(windows)]
fn append_quoted_argument(output: &mut Vec<u16>, value: &[u16]) {
    output.push(b'"' as u16);
    let mut backslashes = 0;
    for unit in value {
        if *unit == b'\\' as u16 {
            backslashes += 1;
        } else if *unit == b'"' as u16 {
            output.extend(std::iter::repeat_n(b'\\' as u16, backslashes * 2 + 1));
            output.push(*unit);
            backslashes = 0;
        } else {
            output.extend(std::iter::repeat_n(b'\\' as u16, backslashes));
            output.push(*unit);
            backslashes = 0;
        }
    }
    output.extend(std::iter::repeat_n(b'\\' as u16, backslashes * 2));
    output.push(b'"' as u16);
}

#[cfg(windows)]
fn environment_block() -> Result<Vec<u16>, crate::ProtocolError> {
    use std::os::windows::ffi::OsStrExt;

    let mut entries = Vec::new();
    for (key, value) in std::env::vars_os() {
        let key_text = key.to_string_lossy().into_owned();
        if key_text.eq_ignore_ascii_case("AIGUARD_API_KEY")
            || key_text.eq_ignore_ascii_case("AIGUARD_TOKEN")
        {
            continue;
        }
        let key_units: Vec<u16> = key.encode_wide().collect();
        let value_units: Vec<u16> = value.encode_wide().collect();
        if key_units.is_empty()
            || key_units.contains(&0)
            || value_units.contains(&0)
            || key_units.contains(&(b'=' as u16))
        {
            return unavailable();
        }
        let mut entry = Vec::with_capacity(key_units.len() + value_units.len() + 2);
        entry.extend_from_slice(&key_units);
        entry.push(b'=' as u16);
        entry.extend_from_slice(&value_units);
        entry.push(0);
        entries.push((key_text.to_uppercase(), entry));
    }
    entries.sort_by(|left, right| left.0.cmp(&right.0));
    let mut block = Vec::new();
    for (_, entry) in entries {
        block.extend_from_slice(&entry);
    }
    block.push(0);
    Ok(block)
}

#[cfg(windows)]
fn wide_os(value: &std::ffi::OsStr) -> Result<Vec<u16>, crate::ProtocolError> {
    use std::os::windows::ffi::OsStrExt;

    let mut wide: Vec<u16> = value.encode_wide().collect();
    if wide.is_empty() || wide.contains(&0) {
        return unavailable();
    }
    wide.push(0);
    Ok(wide)
}

#[cfg(windows)]
fn unavailable<T>() -> Result<T, crate::ProtocolError> {
    Err(crate::ProtocolError::new("broker_unavailable", None))
}
