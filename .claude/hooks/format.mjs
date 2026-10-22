// PostToolUse (Edit|Write|MultiEdit): formatea el archivo editado. Nunca bloquea: si la herramienta no está, sale en silencio.
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";

const input = JSON.parse(readFileSync(0, "utf8"));
const file = input.tool_input?.file_path;
if (!file) process.exit(0);

const root = path.resolve(input.cwd ?? process.cwd());
const rel = path.relative(root, path.resolve(file)).split(path.sep);
const run = (cmd, args, cwd) => spawnSync(`${cmd} ${args.join(" ")}`, { cwd, shell: true, stdio: "ignore" });

if (rel[0] === "backend" && file.endsWith(".py")) {
  const cwd = path.join(root, "backend");
  // `ruff` del PATH o del venv; si no, `python -m ruff`.
  if (run("ruff", ["format", `"${file}"`], cwd).status !== 0) run("python", ["-m", "ruff", "format", `"${file}"`], cwd);
} else if (rel[0] === "web" && /\.(tsx?|jsx?|css|json|md)$/.test(file)) {
  // --no: usa el prettier local de web/node_modules, nunca descarga uno. Respeta web/.prettierignore.
  run("npx", ["--no", "prettier", "--write", `"${file}"`], path.join(root, "web"));
}
