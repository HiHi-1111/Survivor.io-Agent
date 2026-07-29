"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

function readStdin() {
  return fs.readFileSync(0, "utf8");
}

function findChunkRoot(bundleDir) {
  const candidates = [
    path.join(bundleDir, "_next", "static", "chunks"),
    path.join(bundleDir, "sio-tools.exp0.dev", "_next", "static", "chunks"),
    bundleDir,
  ];
  for (const candidate of candidates) {
    if (fs.existsSync(candidate) && fs.statSync(candidate).isDirectory()) {
      if (path.basename(candidate) === "chunks" || fs.existsSync(path.join(candidate, "webpack-dd0440e0d15bea84.js"))) {
        return candidate;
      }
    }
  }
  throw new Error(`Could not find sIO _next/static/chunks under ${bundleDir}`);
}

function walkJavaScript(root) {
  const files = [];
  for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
    const target = path.join(root, entry.name);
    if (entry.isDirectory()) files.push(...walkJavaScript(target));
    else if (entry.name.endsWith(".js") && !entry.name.startsWith("webpack-")) files.push(target);
  }
  return files;
}

function repairCapturedSource(source) {
  // The supplied browser capture inserts spaces inside modern JavaScript operators.
  return source
    .replaceAll("? .", "?.")
    .replaceAll("? ?", "??")
    .replaceAll("|| =", "||=")
    .replaceAll("&& =", "&&=")
    .replaceAll("?? =", "??=");
}

function buildRuntime(chunkRoot) {
  const sandbox = { self: { webpackChunk_N_E: [] }, console };
  sandbox.globalThis = sandbox.self;
  sandbox.window = sandbox.self;
  vm.createContext(sandbox);

  for (const filename of walkJavaScript(chunkRoot)) {
    const source = repairCapturedSource(fs.readFileSync(filename, "utf8"));
    try {
      vm.runInContext(source, sandbox, { filename, timeout: 1500 });
    } catch (_error) {
      // UI-only chunks may reference unsupported syntax or browser build artifacts.
      // Pure calculator modules are loaded from the chunks that parse successfully.
    }
  }

  const modules = {};
  for (const pushed of sandbox.self.webpackChunk_N_E) {
    if (Array.isArray(pushed) && pushed[1]) Object.assign(modules, pushed[1]);
  }
  const cache = {};

  function requireModule(id) {
    const key = String(id);
    if (cache[key]) return cache[key].exports;
    if (!modules[key]) throw new Error(`Missing sIO module ${key}`);
    const module = { exports: {} };
    cache[key] = module;
    modules[key](module, module.exports, requireModule);
    return module.exports;
  }

  requireModule.d = (exports, definitions) => {
    for (const key of Object.keys(definitions)) {
      if (!Object.prototype.hasOwnProperty.call(exports, key)) {
        Object.defineProperty(exports, key, { enumerable: true, get: definitions[key] });
      }
    }
  };
  requireModule.o = (object, property) => Object.prototype.hasOwnProperty.call(object, property);
  requireModule.r = (exports) => {
    if (typeof Symbol !== "undefined" && Symbol.toStringTag) {
      Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });
    }
    Object.defineProperty(exports, "__esModule", { value: true });
  };
  requireModule.n = (module) => {
    const getter = module && module.__esModule ? () => module.default : () => module;
    requireModule.d(getter, { a: getter });
    return getter;
  };
  requireModule.t = (value) => value;
  return requireModule;
}

function defaultStats(stats) {
  return {
    shieldDamageUptime: 1,
    poisonedUptime: 1,
    weakenedUptime: 1,
    chilledUptime: 1,
    lacerationUptime: 1,
    divineFireUptime: 1,
    voidNeckBoost: 1,
    voidNeckBoostUptime: 1,
    voidGlovesInstakill: 1,
    voidBootsBoost: 1,
    chaosBeltBoost: 1,
    hpBulletBoost: 1,
    eternalSuitBoost: 1,
    ...stats,
  };
}

function calculate(calculator, payload) {
  const stats = defaultStats(payload.stats || {});
  const attack = payload.attack || {};
  const damageFactor = payload.damage_factor ?? 1;
  const skillWeights = payload.skill_damage_weights || {};
  const calculation = payload.calculation || "multiplier";
  const selectedPassives = payload.selected_passives || {};
  const passiveMultipliers = payload.passive_multipliers || {};
  const gameMode = payload.game_mode || "ee";
  const value = calculator(
    stats,
    attack,
    damageFactor,
    skillWeights,
    calculation,
    selectedPassives,
    passiveMultipliers,
    gameMode,
  );
  if (!Number.isFinite(value) || value < 0) {
    throw new Error(`sIO calculator returned invalid value: ${value}`);
  }
  return value;
}

function main() {
  try {
    const request = JSON.parse(readStdin());
    const chunkRoot = findChunkRoot(request.bundle_dir);
    const requireModule = buildRuntime(chunkRoot);
    const calculatorModule = requireModule(67727);
    if (!calculatorModule || typeof calculatorModule.f !== "function") {
      throw new Error("sIO calculator module 67727.f was not found");
    }
    const payloads = Array.isArray(request.payloads) ? request.payloads : [];
    const scores = payloads.map((payload) => calculate(calculatorModule.f, payload));
    process.stdout.write(JSON.stringify({ ok: true, scores }));
  } catch (error) {
    process.stdout.write(JSON.stringify({ ok: false, error: String(error && error.stack ? error.stack : error) }));
    process.exitCode = 1;
  }
}

main();
