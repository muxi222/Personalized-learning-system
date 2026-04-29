# Persistent environment bootstrap (idempotent + verbose logging)
# Save as: /home/dataset-assist-0/data/profile.sh
# Usage:
#   source /home/dataset-assist-0/data/profile.sh
#
# Optional env:
#   PROFILE_AUTO_INSTALL=0   # disable auto-install when sourcing
#   PROFILE_AUTO_UPDATE=1    # run mamba/conda update -n base --all (slow)
#   PROFILE_LOG_LEVEL=INFO   # DEBUG|INFO|WARN|ERROR

# -------------------------
# Logging helpers
# -------------------------
__profile_ts() { date "+%Y-%m-%d %H:%M:%S"; }

__profile_color() {
  # $1 = color code
  # only colorize if stdout is a tty
  if [ -t 1 ]; then printf "\033[%sm" "$1"; fi
}

__profile_reset() { if [ -t 1 ]; then printf "\033[0m"; fi }

__profile_level_rank() {
  case "$1" in
    DEBUG) echo 10 ;;
    INFO)  echo 20 ;;
    WARN)  echo 30 ;;
    ERROR) echo 40 ;;
    *)     echo 20 ;;
  esac
}

__profile_log_allowed() {
  local want="${PROFILE_LOG_LEVEL:-INFO}"
  local lvl="$1"
  [ "$(__profile_level_rank "$lvl")" -ge "$(__profile_level_rank "$want")" ]
}

__log() {
  # $1=LEVEL $2=MSG
  local lvl="$1" msg="$2"
  __profile_log_allowed "$lvl" || return 0
  local ts="$(__profile_ts)"
  case "$lvl" in
    DEBUG) __profile_color "90" ;; # gray
    INFO)  __profile_color "36" ;; # cyan
    WARN)  __profile_color "33" ;; # yellow
    ERROR) __profile_color "31" ;; # red
  esac
  printf "[%s] [%s] %s\n" "$ts" "$lvl" "$msg"
  __profile_reset
}

log_debug(){ __log "DEBUG" "$1"; }
log_info(){  __log "INFO"  "$1"; }
log_warn(){  __log "WARN"  "$1"; }
log_error(){ __log "ERROR" "$1"; }

__has_cmd() { command -v "$1" >/dev/null 2>&1; }

__profile_is_sourced() { (return 0 2>/dev/null); }

# -------------------------
# Config
# -------------------------
export PERSIST="/home/dataset-assist-0/data"
export TOOLS="$PERSIST/opt"
export MINIFORGE="$TOOLS/miniforge3"

export PIP_CACHE_DIR="$PERSIST/cache/pip"
export NPM_CONFIG_PREFIX="$PERSIST/npm"

export CONDARC="$PERSIST/condarc"
export CONDA_PKGS_DIRS="$PERSIST/conda/pkgs"
export CONDA_ENVS_PATH="$PERSIST/conda/envs"

# prepend persistent bins
export PATH="$PERSIST/npm/bin:$PERSIST/bin:$PATH"

# -------------------------
# Utilities
# -------------------------
__download() {
  # $1=url $2=out
  local url="$1" out="$2"
  if __has_cmd curl; then
    log_info "Downloading via curl: $url"
    curl -L --retry 3 --retry-delay 1 -o "$out" "$url"
  elif __has_cmd wget; then
    log_info "Downloading via wget: $url"
    wget -O "$out" "$url"
  else
    log_error "Need curl or wget to download: $url"
    return 1
  fi
}

__mkdirs() {
  log_info "Ensuring persistent directories exist under $PERSIST"
  mkdir -p \
    "$TOOLS" \
    "$PERSIST/bin" \
    "$PERSIST/cache/pip" \
    "$PERSIST/conda/pkgs" \
    "$PERSIST/conda/envs" \
    "$PERSIST/npm"
}

__ensure_condarc() {
  if [ -f "$CONDARC" ]; then
    log_debug "condarc already exists: $CONDARC"
    return 0
  fi
  log_info "Creating condarc: $CONDARC"
  cat > "$CONDARC" <<'EOF'
channels:
  - conda-forge
channel_priority: strict
auto_activate_base: false
EOF
}

__bootstrap_miniforge_if_needed() {
  if [ -x "$MINIFORGE/bin/conda" ]; then
    log_info "Miniforge already present: $MINIFORGE"
    return 0
  fi

  local arch installer url out
  arch="$(uname -m)"
  echo "------"
  echo "$arch"
  case "$arch" in
    x86_64)  installer="Miniforge3-25.11.0-1-Linux-x86_64.sh" ;;
    aarch64) installer="Miniforge3-25.11.0-1-Linux-aarch64.sh" ;;
    *)
      log_error "Unsupported arch: $arch"
      return 1
      ;;
  esac

  url="https://github.com/conda-forge/miniforge/releases/latest/download/$installer"
  out="$TOOLS/$installer"

  if [ -f "$out" ]; then
    log_warn "Installer already exists (won't delete): $out"
  else
    log_info "Miniforge not found. Will download installer to: $out"
    __download "$url" "$out" || return 1
    log_info "Downloaded installer: $out"
  fi

  log_info "Installing Miniforge into: $MINIFORGE"
  bash "$out" -b -p "$MINIFORGE" || return 1
  log_info "Miniforge installed successfully."
}

__init_conda() {
  export PATH="$MINIFORGE/bin:$PATH"
  if [ ! -f "$MINIFORGE/etc/profile.d/conda.sh" ]; then
    log_error "conda.sh not found under: $MINIFORGE/etc/profile.d/conda.sh"
    return 1
  fi
  log_info "Initializing conda in current shell"
  # shellcheck disable=SC1091
  source "$MINIFORGE/etc/profile.d/conda.sh"
  log_debug "conda init done. conda version: $(conda --version 2>/dev/null || echo unknown)"
}

__activate_base() {
  log_info "Activating conda environment: base"
  conda activate base >/dev/null 2>&1 || true
  # shellcheck disable=SC2154
  log_debug "Active env: ${CONDA_DEFAULT_ENV:-unknown}"
}

__conda_pkg_installed() {
  # $1=pkg
  local pkg="$1"
  conda list -n base "$pkg" 2>/dev/null | awk -v p="$pkg" '$1==p{found=1} END{exit found?0:1}'
}

__ensure_mamba() {
  if __has_cmd mamba; then
    log_info "mamba already available: $(mamba --version 2>/dev/null || echo ok)"
    return 0
  fi
  log_warn "mamba not found. Installing mamba into base..."
  conda install -n base -y mamba
  if __has_cmd mamba; then
    log_info "mamba installed: $(mamba --version 2>/dev/null || echo ok)"
  else
    log_error "mamba installation finished but command still not found."
    return 1
  fi
}

__maybe_update_all() {
  if [ "${PROFILE_AUTO_UPDATE:-0}" != "1" ]; then
    log_debug "PROFILE_AUTO_UPDATE!=1, skip updating base."
    return 0
  fi
  log_warn "Updating base environment (PROFILE_AUTO_UPDATE=1). This may take time..."
  if __has_cmd mamba; then
    mamba update -n base -y --all
  else
    conda update -n base -y --all
  fi
  log_info "Base environment update completed."
}

__ensure_pkgs_in_base() {
  local wanted_pkgs=(
    git
    python
    nodejs
    pip
#    openssh
    redis-server
    redis-py
    ripgrep
    jq
    cmake
    make
    gcc
    gxx
    pkg-config
  )

  log_info "Checking required packages in conda base..."
  local missing=() p
  for p in "${wanted_pkgs[@]}"; do
    if __conda_pkg_installed "$p"; then
      log_debug "OK: $p"
    else
      log_warn "MISSING: $p"
      missing+=("$p")
    fi
  done

  if [ "${#missing[@]}" -eq 0 ]; then
    log_info "All required packages already installed in base."
    return 0
  fi

  log_warn "Will install missing packages: ${missing[*]}"
  if __has_cmd mamba; then
    mamba install -n base -y "${missing[@]}"
  else
    conda install -n base -y "${missing[@]}"
  fi
  log_info "Package installation completed."
}

__post_pip_upgrade() {
  if __has_cmd python; then
    log_info "Upgrading pip toolchain (pip/setuptools/wheel) inside base (safe/idempotent)"
    python -m pip install -U pip setuptools wheel >/dev/null 2>&1 || true
    log_debug "pip version: $(python -m pip --version 2>/dev/null || echo unknown)"
  else
    log_warn "python not found after setup; skip pip upgrade."
  fi
}

__ensure_persistent_ssh() {
  local persist_ssh="$PERSIST/ssh"
  local home_ssh="$HOME/.ssh"

  log_info "Ensuring persistent SSH directory: $persist_ssh"
  mkdir -p "$persist_ssh"
  chmod 700 "$persist_ssh" 2>/dev/null || true

  # 判断 ~/.ssh 是否“值得备份”
  __ssh_should_backup_home_dir() {
    # 空目录 / 只有 known_hosts 这类可再生文件 -> 不备份
    [ -d "$home_ssh" ] || return 1
    local files
    files="$(ls -A "$home_ssh" 2>/dev/null || true)"

    # 空
    [ -z "$files" ] && return 1

    # 如果包含私钥/公钥/config 等，必须备份
    if ls "$home_ssh"/id_* "$home_ssh"/config "$home_ssh"/authorized_keys >/dev/null 2>&1; then
      return 0
    fi

    # 只有 known_hosts/known_hosts.old 之类 -> 不备份
    # （你也可以把这个列表扩展）
    local nonregen
    nonregen="$(ls -A "$home_ssh" | grep -Ev '^(known_hosts|known_hosts\.old|\.DS_Store)$' || true)"
    [ -n "$nonregen" ] && return 0

    return 1
  }

  # 如果家目录里已有 .ssh 且不是软链
  if [ -e "$home_ssh" ] && [ ! -L "$home_ssh" ]; then
    if __ssh_should_backup_home_dir; then
      local backup="$persist_ssh/_backup_$(date +%Y%m%d_%H%M%S)"
      log_warn "~/.ssh exists and is not a symlink. Backing up to: $backup"
      mkdir -p "$backup"
      cp -a "$home_ssh/." "$backup/" 2>/dev/null || true
    else
      log_info "~/.ssh exists but looks empty/regenerable. Skip backup."
    fi
    rm -rf "$home_ssh" 2>/dev/null || true
  fi

  # 建立软链（幂等）
  if [ -L "$home_ssh" ]; then
    log_debug "~/.ssh is already a symlink."
  else
    log_info "Linking $home_ssh -> $persist_ssh"
    ln -s "$persist_ssh" "$home_ssh"
  fi

  # config（只创建一次）
  if [ ! -f "$persist_ssh/config" ]; then
    log_info "Creating SSH config: $persist_ssh/config"
    cat > "$persist_ssh/config" <<'EOF'
Host *
  IdentitiesOnly yes
  StrictHostKeyChecking accept-new
  UserKnownHostsFile ~/.ssh/known_hosts
  IdentityFile ~/.ssh/id_rsa
EOF
    chmod 600 "$persist_ssh/config" 2>/dev/null || true
  fi

  # key（只生成一次）
  if command -v ssh-keygen >/dev/null 2>&1; then
    local priv="$persist_ssh/id_rsa"
    local pub="$persist_ssh/id_rsa.pub"
    if [ -f "$priv" ] && [ -f "$pub" ]; then
      log_info "SSH key already exists: $pub"
    else
      log_warn "Generating SSH keypair (RSA 4096): $priv"
      ssh-keygen -t rsa -b 4096 -f "$priv" -N "" -C "${USER}@$(hostname)-$(date +%Y%m%d)"
      chmod 600 "$priv" 2>/dev/null || true
      chmod 644 "$pub" 2>/dev/null || true
      log_info "Public key generated: $pub"
    fi
  else
    log_warn "ssh-keygen not found yet (openssh should provide it)."
  fi
}


__ensure_redis_persistent() {
  local rdir="$PERSIST/redis"
  local conf="$rdir/redis.conf"
  local data="$rdir/data"
  local logs="$rdir/logs"
  local pid="$rdir/redis.pid"
  local ctl="$PERSIST/bin/redisctl"

  log_info "Ensuring Redis persistent dirs under: $rdir"
  mkdir -p "$data" "$logs" "$PERSIST/bin"

  if [ ! -f "$conf" ]; then
    log_info "Creating Redis config (first time): $conf"
    cat > "$conf" <<EOF
bind 127.0.0.1
port 6379
protected-mode yes

dir $data
dbfilename dump.rdb

appendonly yes
appendfilename "appendonly.aof"

pidfile $pid
logfile $logs/redis.log

# Keep it simple for dev VM
timeout 0
tcp-keepalive 300
EOF
  else
    log_debug "Redis config exists: $conf"
  fi

  # create redisctl helper (idempotent, only overwrite if missing)
  if [ ! -f "$ctl" ]; then
    log_info "Creating helper: $ctl"
    cat > "$ctl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

PERSIST="/home/dataset-assist-0/data"
CONF="$PERSIST/redis/redis.conf"
PID="$PERSIST/redis/redis.pid"

need_cmd() { command -v "$1" >/dev/null 2>&1 || { echo "Missing command: $1"; exit 1; }; }

is_running() {
  if [ -f "$PID" ] && kill -0 "$(cat "$PID" 2>/dev/null)" 2>/dev/null; then
    return 0
  fi
  # fallback: redis-cli ping
  if command -v redis-cli >/dev/null 2>&1; then
    redis-cli -h 127.0.0.1 -p 6379 ping >/dev/null 2>&1 && return 0 || true
  fi
  return 1
}

case "${1:-}" in
  start)
    need_cmd redis-server
    if is_running; then
      echo "[redisctl] Redis already running."
      exit 0
    fi
    echo "[redisctl] Starting redis-server with $CONF"
    redis-server "$CONF" >/dev/null 2>&1 &
    sleep 0.2
    if is_running; then
      echo "[redisctl] Started."
    else
      echo "[redisctl] Start failed. Check log: $PERSIST/redis/logs/redis.log"
      exit 1
    fi
    ;;
  stop)
    if is_running; then
      echo "[redisctl] Stopping..."
      redis-cli -h 127.0.0.1 -p 6379 shutdown || true
      sleep 0.2
      echo "[redisctl] Stopped."
    else
      echo "[redisctl] Not running."
    fi
    ;;
  status)
    if is_running; then
      echo "[redisctl] Running."
      redis-cli -h 127.0.0.1 -p 6379 info server | head -n 20 || true
    else
      echo "[redisctl] Not running."
      exit 1
    fi
    ;;
  cli)
    need_cmd redis-cli
    exec redis-cli -h 127.0.0.1 -p 6379
    ;;
  *)
    echo "Usage: redisctl {start|stop|status|cli}"
    exit 2
    ;;
esac
EOF
    chmod +x "$ctl"
  else
    log_debug "redisctl exists: $ctl"
  fi

  log_info "Redis persistent setup ready. Use: redisctl start"
}


__redis_autostart() {
  # default: auto start
  if [ "${PROFILE_REDIS_AUTOSTART:-1}" != "1" ]; then
    log_warn "PROFILE_REDIS_AUTOSTART=0 -> skip redis autostart."
    return 0
  fi

  # only try if redisctl exists (created by __ensure_redis_persistent)
  local ctl="$PERSIST/bin/redisctl"
  if [ ! -x "$ctl" ]; then
    log_warn "redisctl not found yet: $ctl (skip autostart)"
    return 0
  fi

  # only try if redis-server command exists
  if ! command -v redis-server >/dev/null 2>&1; then
    log_warn "redis-server not found (maybe PROFILE_AUTO_INSTALL=0). Skip autostart."
    return 0
  fi

  log_info "Auto-starting Redis..."
  "$ctl" start || log_warn "Redis autostart failed. Check: $PERSIST/redis/logs/redis.log"
}


__print_summary() {
  log_info "Environment ready."
  log_info "Quick check:"
  echo "  conda : $(conda --version 2>/dev/null || echo 'N/A')"
  echo "  mamba : $(mamba --version 2>/dev/null || echo 'N/A')"
  echo "  git   : $(git --version 2>/dev/null || echo 'N/A')"
  echo "  python: $(python --version 2>/dev/null || echo 'N/A')"
  echo "  node  : $(node --version 2>/dev/null || echo 'N/A')"
  echo "  npm   : $(npm --version 2>/dev/null || echo 'N/A')"
}

# -------------------------
# Main
# -------------------------
if ! __profile_is_sourced; then
  log_warn "This script is intended to be sourced, not executed."
  log_warn "Use: source $PERSIST/profile.sh"
fi

log_info "========== [profile.sh] start =========="
log_info "PERSIST=$PERSIST"
log_info "TOOLS=$TOOLS"
log_info "MINIFORGE=$MINIFORGE"
log_info "PROFILE_AUTO_INSTALL=${PROFILE_AUTO_INSTALL:-1}, PROFILE_AUTO_UPDATE=${PROFILE_AUTO_UPDATE:-0}, PROFILE_LOG_LEVEL=${PROFILE_LOG_LEVEL:-INFO}"

__mkdirs || { log_error "mkdirs failed"; return 1; }
__ensure_condarc || { log_error "ensure_condarc failed"; return 1; }
__bootstrap_miniforge_if_needed || { log_error "bootstrap_miniforge failed"; return 1; }
__init_conda || { log_error "init_conda failed"; return 1; }
__activate_base

BOOTSTRAP_MARK="$PERSIST/.bootstrap_done"

if [ "${PROFILE_AUTO_INSTALL:-1}" = "1" ]; then
  if [ ! -f "$BOOTSTRAP_MARK" ] || [ "${PROFILE_FORCE_INSTALL:-0}" = "1" ]; then
    __ensure_mamba || { log_error "ensure_mamba failed"; return 1; }
    __maybe_update_all || { log_error "maybe_update_all failed"; return 1; }
    __ensure_pkgs_in_base || { log_error "ensure_pkgs_in_base failed"; return 1; }
    __post_pip_upgrade

    date "+%F %T" > "$BOOTSTRAP_MARK"
    log_info "Bootstrap done. Marked at $BOOTSTRAP_MARK"
  else
    log_info "Bootstrap already done ($(cat "$BOOTSTRAP_MARK")). Skip installs."
  fi

  # 这些属于“每次都要保证可用”的轻量动作，可以放在外面
#  __ensure_persistent_ssh || { log_error "ensure_persistent_ssh failed"; return 1; }
  __ensure_redis_persistent || { log_error "ensure_redis_persistent failed"; return 1; }
  __redis_autostart
else
  log_warn "PROFILE_AUTO_INSTALL=0 -> skip auto dependency install."
fi


__print_summary
log_info "========== [profile.sh] done =========="


# ===== git aliases (bash/zsh) =====
alias gitst='git status'
alias gitp='git pull'
alias gitl='git log'
alias gitlp='git log -p'
alias gitco='git checkout'
alias gitpm='git pull origin master'
alias gitrh='git reset --hard origin/master'

# ===== conda hook + activate =====
# 让 conda activate 在当前 shell 生效（不依赖 conda init 修改 rc 文件）
if [ -n "${MINIFORGE:-}" ] && [ -r "${MINIFORGE}/etc/profile.d/conda.sh" ]; then
  # profile.sh 里已经 export MINIFORGE 的话，这条就能用
  . "${MINIFORGE}/etc/profile.d/conda.sh"
elif command -v conda >/dev/null 2>&1; then
  # 兜底：通过 conda 自己生成 shell hook（bash/zsh 都支持）
  __conda_setup="$("conda" "shell.${SHELL##*/}" "hook" 2>/dev/null || true)"
  if [ -n "$__conda_setup" ]; then
    eval "$__conda_setup"
  fi
  unset __conda_setup
fi

# 激活你的环境（不存在就跳过，不报错）
if command -v conda >/dev/null 2>&1; then
  conda activate 312_edu >/dev/null 2>&1 || true
fi

export http_proxy=socks5h://127.0.0.1:10800
export https_proxy=socks5h://127.0.0.1:10800

export PATH="/home/dataset-assist-0/data/opt/miniforge3/bin:$PATH"

env -u ALL_PROXY -u all_proxy -u HTTP_PROXY -u http_proxy -u HTTPS_PROXY -u https_proxy pip install 'httpx[socks]' socksio

export NO_PROXY=127.0.0.1,localhost
