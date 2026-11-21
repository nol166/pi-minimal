// Print what pi's own package manager resolves for (agentDir, cwd), as JSON.
// Used by test_pi_parity.py: PI_PKG is the installed pi-coding-agent package directory.
// The project is treated as trusted, which is what pi does once you accept its prompt.
import { readFileSync, existsSync } from "node:fs";
import { join } from "node:path";

const PI = process.env.PI_PKG;
const { DefaultPackageManager } = await import(join(PI, "dist/core/package-manager.js"));

const [agentDir, cwd] = process.argv.slice(2);
const read = (p) => (existsSync(p) ? JSON.parse(readFileSync(p, "utf8")) : {});
const globalSettings = read(join(agentDir, "settings.json"));

// nearest ancestor .pi/settings.json, like pi's project settings lookup
let projectSettings = {};
for (let d = cwd; ; ) {
  const p = join(d, ".pi", "settings.json");
  if (existsSync(p)) { projectSettings = read(p); break; }
  const parent = join(d, "..");
  if (parent === d) break;
  d = parent;
}

const settingsManager = {
  getGlobalSettings: () => globalSettings,
  getProjectSettings: () => projectSettings,
  isProjectTrusted: () => true,
};

const pm = new DefaultPackageManager({
  cwd, agentDir, settingsManager,
  builtinExtensions: ["mcp", "llama.cpp", "codemode", "tool-search"],
  commandOutput: "ignore",
});
const res = await pm.resolve(() => {});
console.log(JSON.stringify({ extensions: res.extensions, skills: res.skills }));
