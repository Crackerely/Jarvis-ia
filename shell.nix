{ pkgs ? import <nixpkgs> {} }:

pkgs.mkShell {
  buildInputs = with pkgs; [
    python3
    python3Packages.pyaudio

    portaudio
    alsa-utils
  ];

  shellHook = ''
    echo "Entorno listo para pruebas de micrófono."
  '';
}
