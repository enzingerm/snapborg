{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.11";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
      ...
    }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
      in
      {
        packages = {
          default = pkgs.python3.pkgs.buildPythonApplication rec {
            pname = "snapborg";
            version = "0.1.0";
            pyproject = true;

            src = ./.;

            # Specify the Python dependencies
            propagatedBuildInputs = [
              # Add any required Python packages here
              pkgs.python3Packages.pyyaml
              pkgs.python3Packages.packaging
              pkgs.borgbackup
              pkgs.snapper
            ];

            build-system = [ pkgs.python3.pkgs.setuptools ];

            meta = with nixpkgs.lib; {
              homepage = "https://github.com/enzingerm/snapborg";
              license = licenses.gpl3; # Update with the correct license
            };
          };
        };

      }
    );
}
