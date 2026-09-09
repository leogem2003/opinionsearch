{
  description = "Python development environment with Astral uv and PostgreSQL";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = { self, nixpkgs }:
    let
      supportedSystems = [ "x86_64-linux" "aarch64-linux" "x86_64-darwin" "aarch64-darwin" ];
      forEachSystem = f: nixpkgs.lib.genAttrs supportedSystems (system: f {
        pkgs = import nixpkgs { inherit system; };
      });
    in
    {
      devShells = forEachSystem ({ pkgs }: 
        let
          pgWithPlugins = pkgs.postgresql.withPackages (p: with p; [
            postgis
            pgvector
          ]);
        in
        {
          default = pkgs.mkShell {
            packages = with pkgs; [
              python3
              uv
              gdal
              geos
              proj
              pgWithPlugins
            ];
            
            shellHook = ''
              export UV_PYTHON_PREFERENCE="system"
              export LD_LIBRARY_PATH="${pkgs.lib.makeLibraryPath (with pkgs; [ gdal geos proj ])}:$LD_LIBRARY_PATH"
              
              # --- PostgreSQL Setup ---
              
              export PGDATA="$PWD/.pgdata"
              # Connect via TCP to localhost on the default port (5432)
              export PGHOST="localhost"
              export PGPORT="5432"
              export PGDATABASE="opinionsearch"

              if [ ! -d "$PGDATA" ]; then
                echo "Initializing PostgreSQL database..."
                initdb --auth=trust --no-locale --encoding=UTF8
                
                # Start the server temporarily to set up the DB and extensions
                pg_ctl start -l "$PGDATA/pg.log" -o "-k $PGDATA"
                
                echo "Creating role, database, and extensions..."
                # 1. Create the user (role) with superuser permissions
                createuser -s "$PGDATABASE"
                
                # 2. Create the database and assign ownership to the new user
                createdb -O "$PGDATABASE" "$PGDATABASE"
                
                # 3. Create the required extensions
                psql -d "$PGDATABASE" -c "CREATE EXTENSION postgis;"
                psql -d "$PGDATABASE" -c "CREATE EXTENSION vector;"
                
                # 4. Initial migration
                uv run python manage.py migrate
                uv run python manage.py createsuperuser
                
                pg_ctl stop -m fast
              fi

              echo "Starting PostgreSQL on port 5432..."
              pg_ctl start -l "$PGDATA/pg.log" -o "-k $PGDATA"

              trap 'echo "Stopping PostgreSQL..."; pg_ctl stop -m fast' EXIT
            '';
          };
        });
    };
}