{
  description = "gh runners: a gh extension to watch and register self-hosted GitHub Actions runners";

  inputs.nixpkgs.url = "https://channels.nixos.org/nixpkgs-unstable/nixexprs.tar.xz";

  outputs =
    { self, nixpkgs }:
    let
      forAllSystems = nixpkgs.lib.genAttrs [
        "aarch64-darwin"
        "x86_64-darwin"
        "aarch64-linux"
        "x86_64-linux"
      ];
    in
    {
      # Use as programs.gh.extensions = [ gh-runners.packages.${system}.default ]; in Home Manager.
      packages = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
        in
        {
          default = pkgs.writeShellApplication {
            name = "gh-runners";
            text = builtins.readFile ./gh-runners;
            meta = {
              description = "gh extension to watch and register self-hosted GitHub Actions runners";
              license = pkgs.lib.licenses.mit;
              mainProgram = "gh-runners";
            };
          };
        }
      );

      checks = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
        in
        {
          default =
            pkgs.runCommand "gh-runners-tests"
              {
                nativeBuildInputs = [
                  pkgs.jq
                  pkgs.python3
                ];
              }
              ''
                cp -r ${self}/. src && chmod -R u+w src
                patchShebangs src
                python3 src/tests/test_gh_runners.py
                touch $out
              '';
          package = self.packages.${system}.default;
        }
      );

      formatter = forAllSystems (system: nixpkgs.legacyPackages.${system}.nixfmt);
    };
}
