!macro NSIS_HOOK_POSTINSTALL
  ExecWait '"$INSTDIR\aiguard-native-host-manager.exe" install nsis' $0
  ${If} $0 != 0
    Abort "AI Guard native host registration failed."
  ${EndIf}
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  ExecWait '"$INSTDIR\aiguard-native-host-manager.exe" uninstall nsis' $0
  ${If} $0 != 0
    Abort "AI Guard native host unregistration failed."
  ${EndIf}
!macroend
