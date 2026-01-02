{
  lib,
  pkgs,
  pythonPackages,
  src,
  ...
}:
let
  version_file = builtins.readFile "${src}/snapborg/version.py";
  version_match = builtins.match ".*__version__ = \"([0-9A-Za-z.+-]+)\".*" version_file;
  version = builtins.head version_match;
in
pythonPackages.buildPythonApplication rec {
  pname = "snapborg";
  pyproject = true;
  inherit src;
  inherit version;

  propagatedBuildInputs = with pkgs; [
    borgbackup
    snapper
    pythonPackages.pyyaml
  ];

  nativeBuildInputs = with pythonPackages; [
    setuptools
    packaging
  ];

  meta = with lib; {
    homepage = "https://github.com/enzingerm/snapborg";
    license = licenses.gpl3;
  };
}
