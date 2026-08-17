!define AIGUARD_HOOK_DIR "${__FILEDIR__}"

Var AIGUARD_TRANSACTION_TOKEN

!macro AIGUARD_ABORT_FIXED_STAGE EXIT_CODE FAILURE_KIND
  ${If} ${EXIT_CODE} != 0
    ; The process exit code is the authoritative classification channel.
    ; Stdout may be empty under nsExec on otherwise valid Windows hosts.
    ${If} ${EXIT_CODE} == 11
      Abort "AI Guard ${FAILURE_KIND} failed (D11 install root)."
    ${ElseIf} ${EXIT_CODE} == 12
      Abort "AI Guard ${FAILURE_KIND} failed (D12 PowerShell runtime)."
    ${ElseIf} ${EXIT_CODE} == 13
      Abort "AI Guard ${FAILURE_KIND} failed (D13 control state)."
    ${ElseIf} ${EXIT_CODE} == 14
      Abort "AI Guard ${FAILURE_KIND} failed (D14 component conflict)."
    ${ElseIf} ${EXIT_CODE} == 15
      Abort "AI Guard ${FAILURE_KIND} failed (D15 process drain)."
    ${ElseIf} ${EXIT_CODE} == 16
      Abort "AI Guard ${FAILURE_KIND} failed (D16 component cleanup)."
    ${ElseIf} ${EXIT_CODE} == 17
      Abort "AI Guard ${FAILURE_KIND} failed (D17 payload validation)."
    ${ElseIf} ${EXIT_CODE} == 1
      Abort "AI Guard ${FAILURE_KIND} failed (D12 PowerShell runtime)."
    ${ElseIf} ${EXIT_CODE} == "error"
      Abort "AI Guard ${FAILURE_KIND} failed (D12 PowerShell runtime)."
    ${ElseIf} ${EXIT_CODE} == "timeout"
      Abort "AI Guard ${FAILURE_KIND} failed (D12 PowerShell runtime)."
    ${Else}
      Abort "AI Guard ${FAILURE_KIND} failed (D10 unclassified)."
    ${EndIf}
  ${EndIf}
!macroend

!macro AIGUARD_ACQUIRE_PACKAGE_LOCK
  ; One per-user product file serializes every supported install root across
  ; console/RDP sessions. Delete-on-close leaves no lock state.
  System::Call 'kernel32::CreateFileW(w "$LOCALAPPDATA\AI Guard.aiguard-package-lifecycle-v1.lock", i 0xC0010000, i 0, p 0, i 4, i 0x04200002, p 0) p .r9'
  ${If} $9 == -1
    Abort "Another AI Guard package transaction is active."
  ${EndIf}
!macroend

!macro AIGUARD_WAIT_AND_REMOVE_LAUNCHERS
  ; Pass the root as process data so quote-bearing custom paths cannot become
  ; PowerShell source. The embedded fixed script isolates launchers first.
  System::Call 'kernel32::SetEnvironmentVariableW(w "AIGUARD_INTERNAL_INSTALL_ROOT", w "$INSTDIR") i .r8'
  ${If} $8 == 0
    Abort "AI Guard native component drain failed (D11 install root)."
  ${EndIf}
  SetOutPath "$PLUGINSDIR"
  File /oname=aiguard-native-component-drain.ps1 "${AIGUARD_HOOK_DIR}\native-component-drain.ps1"
  ; Avoid the NSIS System.dll in $PLUGINSDIR shadowing .NET references used by Add-Type.
  SetOutPath "$INSTDIR"
  nsExec::ExecToStack `"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -File "$PLUGINSDIR\aiguard-native-component-drain.ps1"`
  Pop $0
  Pop $7
  Delete "$PLUGINSDIR\aiguard-native-component-drain.ps1"
  System::Call 'kernel32::SetEnvironmentVariableW(w "AIGUARD_INTERNAL_INSTALL_ROOT", p 0) i .r8'
  SetOutPath "$INSTDIR"
  !insertmacro AIGUARD_ABORT_FIXED_STAGE $0 "native component drain"
!macroend

!macro AIGUARD_NORMALIZE_PACKAGE_PAYLOAD
  ; Tauri extracts through the NSIS token, whose default object owner can
  ; differ from its user SID. Normalize only the fixed payload before the
  ; ordinary manager performs its strict manifest and digest admission.
  System::Call 'kernel32::SetEnvironmentVariableW(w "AIGUARD_INTERNAL_INSTALL_ROOT", w "$INSTDIR") i .r8'
  ${If} $8 == 0
    Abort "AI Guard native payload validation failed (D11 install root)."
  ${EndIf}
  SetOutPath "$PLUGINSDIR"
  File /oname=aiguard-native-component-drain.ps1 "${AIGUARD_HOOK_DIR}\native-component-drain.ps1"
  SetOutPath "$INSTDIR"
  nsExec::ExecToStack `"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -File "$PLUGINSDIR\aiguard-native-component-drain.ps1" -Mode NormalizePayload`
  Pop $0
  Pop $7
  Delete "$PLUGINSDIR\aiguard-native-component-drain.ps1"
  System::Call 'kernel32::SetEnvironmentVariableW(w "AIGUARD_INTERNAL_INSTALL_ROOT", p 0) i .r8'
  SetOutPath "$INSTDIR"
  !insertmacro AIGUARD_ABORT_FIXED_STAGE $0 "native payload validation"
!macroend

!macro NSIS_HOOK_PREINSTALL
  !insertmacro AIGUARD_ACQUIRE_PACKAGE_LOCK
  StrCpy $AIGUARD_TRANSACTION_TOKEN ""
  IfFileExists "$INSTDIR\aiguard-native-host-manager.exe" 0 aiguard_preinstall_no_manager
  ExecWait '"$INSTDIR\aiguard-native-host-manager.exe" capability nsis' $8
  nsExec::ExecToStack '"$INSTDIR\aiguard-native-host-manager.exe" drain nsis'
  Pop $0
  Pop $AIGUARD_TRANSACTION_TOKEN
  ${If} $0 == 0
    Goto aiguard_wait_old_processes
  ${EndIf}
  ${If} $8 == 0
    Abort "AI Guard native component drain failed (D18 manager drain)."
  ${EndIf}
  ; The pre-Slice-6 manager has no drain action. Establish the fixed barrier
  ; and remove the old host discovery before waiting for every old product
  ; executable to exit. This prevents a legacy storefront from starting a new
  ; native path after the zero-process proof.
  Goto aiguard_create_or_validate_marker
  aiguard_preinstall_no_manager:
  IfFileExists "$INSTDIR\.aiguard-component-maintenance-v1" aiguard_create_or_validate_marker 0
  IfFileExists "$INSTDIR\aiguard-native-broker.exe" aiguard_create_or_validate_marker 0
  Goto aiguard_create_or_validate_marker
  aiguard_create_or_validate_marker:
  IfFileExists "$INSTDIR\.aiguard-component-maintenance-v1" aiguard_marker_exists 0
  ClearErrors
  FileOpen $1 "$INSTDIR\.aiguard-component-maintenance-v1" w
  ${If} ${Errors}
    Abort "AI Guard native component drain failed (D13 control state)."
  ${EndIf}
  FileWrite $1 "AIGUARD_COMPONENT_MAINTENANCE_V1$\n"
  FileClose $1
  ; Close publishes the fixed bytes. Reopen through the same validation path
  ; before treating the replacement barrier as established.
  Goto aiguard_marker_exists
  aiguard_marker_exists:
  ClearErrors
  FileOpen $1 "$INSTDIR\.aiguard-component-maintenance-v1" r
  ${If} ${Errors}
    Abort "AI Guard native component drain failed (D13 control state)."
  ${EndIf}
  FileRead $1 $2
  FileRead $1 $3
  FileClose $1
  ${If} $2 != "AIGUARD_COMPONENT_MAINTENANCE_V1$\n"
  ${OrIf} $3 != ""
    Abort "AI Guard native component drain failed (D13 control state)."
  ${EndIf}
  ; Validate only exact product-owned discovery. Launcher quarantine makes the
  ; existing path undiscoverable during the proof, while an aborted proof can
  ; restore the old installation without reconstructing registry state.
  SetRegView 64
  ReadRegStr $4 HKCU "Software\Google\Chrome\NativeMessagingHosts\th.ac.psu.aiguard.native_host" ""
  ${If} $4 != ""
    ${If} $4 != "$INSTDIR\th.ac.psu.aiguard.native_host.json"
      Abort "AI Guard legacy native host isolation failed."
    ${EndIf}
  ${EndIf}
  ReadRegStr $4 HKCU "Software\Chromium\NativeMessagingHosts\th.ac.psu.aiguard.native_host" ""
  ${If} $4 != ""
    ${If} $4 != "$INSTDIR\th.ac.psu.aiguard.native_host.json"
      Abort "AI Guard legacy native host isolation failed."
    ${EndIf}
  ${EndIf}
  DeleteRegKey HKCU "Software\Google\Chrome\NativeMessagingHosts\th.ac.psu.aiguard.native_host"
  DeleteRegKey HKCU "Software\Chromium\NativeMessagingHosts\th.ac.psu.aiguard.native_host"
  SetRegView 32
  ReadRegStr $4 HKCU "Software\Google\Chrome\NativeMessagingHosts\th.ac.psu.aiguard.native_host" ""
  ${If} $4 != ""
    ${If} $4 != "$INSTDIR\th.ac.psu.aiguard.native_host.json"
      Abort "AI Guard legacy native host isolation failed."
    ${EndIf}
  ${EndIf}
  ReadRegStr $4 HKCU "Software\Chromium\NativeMessagingHosts\th.ac.psu.aiguard.native_host" ""
  ${If} $4 != ""
    ${If} $4 != "$INSTDIR\th.ac.psu.aiguard.native_host.json"
      Abort "AI Guard legacy native host isolation failed."
    ${EndIf}
  ${EndIf}
  DeleteRegKey HKCU "Software\Google\Chrome\NativeMessagingHosts\th.ac.psu.aiguard.native_host"
  DeleteRegKey HKCU "Software\Chromium\NativeMessagingHosts\th.ac.psu.aiguard.native_host"
  SetRegView 64
  aiguard_wait_old_processes:
  !insertmacro AIGUARD_WAIT_AND_REMOVE_LAUNCHERS
!macroend

!macro NSIS_HOOK_POSTINSTALL
  !insertmacro AIGUARD_NORMALIZE_PACKAGE_PAYLOAD
  ${If} $AIGUARD_TRANSACTION_TOKEN == ""
    ; A fresh installer process has no in-memory token after an interrupted
    ; replacement. The admitted new manager reloads only an exact receipt.
    nsExec::ExecToStack '"$INSTDIR\aiguard-native-host-manager.exe" resume-package nsis'
    Pop $0
    Pop $AIGUARD_TRANSACTION_TOKEN
    ${If} $0 == 0
      ExecWait '"$INSTDIR\aiguard-native-host-manager.exe" complete nsis "$AIGUARD_TRANSACTION_TOKEN"' $0
    ${Else}
      StrCpy $AIGUARD_TRANSACTION_TOKEN ""
      ExecWait '"$INSTDIR\aiguard-native-host-manager.exe" complete-legacy nsis' $0
    ${EndIf}
  ${Else}
    ExecWait '"$INSTDIR\aiguard-native-host-manager.exe" complete nsis "$AIGUARD_TRANSACTION_TOKEN"' $0
  ${EndIf}
  ${If} $0 != 0
    Abort "AI Guard native host registration failed."
  ${EndIf}
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  !insertmacro AIGUARD_ACQUIRE_PACKAGE_LOCK
  StrCpy $AIGUARD_TRANSACTION_TOKEN ""
  IfFileExists "$INSTDIR\.aiguard-component-transaction-v1" 0 aiguard_begin_remove
  IfFileExists "$INSTDIR\.aiguard-component-maintenance-v1" aiguard_recover_remove 0
  aiguard_begin_remove:
  nsExec::ExecToStack '"$INSTDIR\aiguard-native-host-manager.exe" remove nsis'
  Pop $0
  Pop $AIGUARD_TRANSACTION_TOKEN
  ${If} $0 != 0
    Abort "AI Guard native host unregistration failed."
  ${EndIf}
  Goto aiguard_wait_remove_processes
  aiguard_recover_remove:
  ; A new uninstaller process resumes only exact package-owned state. The
  ; manager completed registration removal before launcher deletion began.
  ClearErrors
  FileOpen $1 "$INSTDIR\.aiguard-component-transaction-v1" r
  ${If} ${Errors}
    Abort "AI Guard native component transaction was invalid."
  ${EndIf}
  FileRead $1 $2
  FileRead $1 $3
  FileClose $1
  StrCpy $AIGUARD_TRANSACTION_TOKEN $2 -1
  ${If} $2 != "$AIGUARD_TRANSACTION_TOKEN$\n"
  ${OrIf} $3 != ""
    Abort "AI Guard native component transaction was invalid."
  ${EndIf}
  StrLen $4 $AIGUARD_TRANSACTION_TOKEN
  ${If} $4 != 64
    Abort "AI Guard native component transaction was invalid."
  ${EndIf}
  StrCpy $4 0
  aiguard_uninstall_token_loop:
  StrCpy $5 $AIGUARD_TRANSACTION_TOKEN 1 $4
  StrCmp $5 "0" aiguard_uninstall_token_character
  StrCmp $5 "1" aiguard_uninstall_token_character
  StrCmp $5 "2" aiguard_uninstall_token_character
  StrCmp $5 "3" aiguard_uninstall_token_character
  StrCmp $5 "4" aiguard_uninstall_token_character
  StrCmp $5 "5" aiguard_uninstall_token_character
  StrCmp $5 "6" aiguard_uninstall_token_character
  StrCmp $5 "7" aiguard_uninstall_token_character
  StrCmp $5 "8" aiguard_uninstall_token_character
  StrCmp $5 "9" aiguard_uninstall_token_character
  StrCmp $5 "a" aiguard_uninstall_token_character
  StrCmp $5 "b" aiguard_uninstall_token_character
  StrCmp $5 "c" aiguard_uninstall_token_character
  StrCmp $5 "d" aiguard_uninstall_token_character
  StrCmp $5 "e" aiguard_uninstall_token_character
  StrCmp $5 "f" aiguard_uninstall_token_character
  Abort "AI Guard native component transaction was invalid."
  aiguard_uninstall_token_character:
  IntOp $4 $4 + 1
  StrCmp $4 64 aiguard_uninstall_token_valid aiguard_uninstall_token_loop
  aiguard_uninstall_token_valid:
  ClearErrors
  FileOpen $1 "$INSTDIR\.aiguard-component-maintenance-v1" r
  ${If} ${Errors}
    Abort "AI Guard native component drain was invalid."
  ${EndIf}
  FileRead $1 $2
  FileRead $1 $3
  FileClose $1
  ${If} $2 != "AIGUARD_COMPONENT_MAINTENANCE_V1$\n"
  ${OrIf} $3 != ""
    Abort "AI Guard native component drain was invalid."
  ${EndIf}
  ; Recovery accepts absent registration or this exact product root only.
  SetRegView 64
  ReadRegStr $4 HKCU "Software\Google\Chrome\NativeMessagingHosts\th.ac.psu.aiguard.native_host" ""
  ${If} $4 != ""
  ${AndIf} $4 != "$INSTDIR\th.ac.psu.aiguard.native_host.json"
    Abort "AI Guard native host unregistration failed."
  ${EndIf}
  ReadRegStr $4 HKCU "Software\Chromium\NativeMessagingHosts\th.ac.psu.aiguard.native_host" ""
  ${If} $4 != ""
  ${AndIf} $4 != "$INSTDIR\th.ac.psu.aiguard.native_host.json"
    Abort "AI Guard native host unregistration failed."
  ${EndIf}
  DeleteRegKey HKCU "Software\Google\Chrome\NativeMessagingHosts\th.ac.psu.aiguard.native_host"
  DeleteRegKey HKCU "Software\Chromium\NativeMessagingHosts\th.ac.psu.aiguard.native_host"
  SetRegView 32
  ReadRegStr $4 HKCU "Software\Google\Chrome\NativeMessagingHosts\th.ac.psu.aiguard.native_host" ""
  ${If} $4 != ""
  ${AndIf} $4 != "$INSTDIR\th.ac.psu.aiguard.native_host.json"
    Abort "AI Guard native host unregistration failed."
  ${EndIf}
  ReadRegStr $4 HKCU "Software\Chromium\NativeMessagingHosts\th.ac.psu.aiguard.native_host" ""
  ${If} $4 != ""
  ${AndIf} $4 != "$INSTDIR\th.ac.psu.aiguard.native_host.json"
    Abort "AI Guard native host unregistration failed."
  ${EndIf}
  DeleteRegKey HKCU "Software\Google\Chrome\NativeMessagingHosts\th.ac.psu.aiguard.native_host"
  DeleteRegKey HKCU "Software\Chromium\NativeMessagingHosts\th.ac.psu.aiguard.native_host"
  SetRegView 64
  aiguard_wait_remove_processes:
  !insertmacro AIGUARD_WAIT_AND_REMOVE_LAUNCHERS
!macroend

!macro NSIS_HOOK_POSTUNINSTALL
  ${If} $AIGUARD_TRANSACTION_TOKEN == ""
    Abort "AI Guard native component transaction was lost."
  ${EndIf}
  FileOpen $1 "$INSTDIR\.aiguard-component-transaction-v1" r
  FileRead $1 $2
  FileRead $1 $3
  FileClose $1
  ${If} $2 != "$AIGUARD_TRANSACTION_TOKEN$\n"
  ${OrIf} $3 != ""
    Abort "AI Guard native component transaction was invalid."
  ${EndIf}
  FileOpen $1 "$INSTDIR\.aiguard-component-maintenance-v1" r
  FileRead $1 $2
  FileRead $1 $3
  FileClose $1
  ${If} $2 != "AIGUARD_COMPONENT_MAINTENANCE_V1$\n"
  ${OrIf} $3 != ""
    Abort "AI Guard native component drain was invalid."
  ${EndIf}
  Delete "$INSTDIR\.aiguard-component-maintenance-v1"
  Delete "$INSTDIR\.aiguard-component-transaction-v1"
  ; PREUNINSTALL used the install root as its working directory. Leave it
  ; before removing the now-empty root or Windows retains that directory.
  SetOutPath "$PLUGINSDIR"
  ClearErrors
  RMDir "$INSTDIR"
  ${If} ${Errors}
    Abort "AI Guard native component cleanup failed."
  ${EndIf}
!macroend
