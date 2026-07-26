-- typed-jinja language server: static type checking for Jinja templates.
--
-- Install: copy this file to ~/.config/nvim/lsp/typed_jinja.lua, then in your config:
--   vim.lsp.enable('typed_jinja')
--
-- Filetype detection for templates (add once to your config):
--   vim.filetype.add({
--     extension = { jinja = 'jinja' },
--     pattern = { ['.*%.html%.jinja'] = 'jinja' },
--   })
--
-- The default cmd assumes `typed-jinja-lsp` is on PATH (an active venv, or `uv sync`).
-- For a project-local venv without activation, swap cmd for a resolver like:
--   cmd = function(dispatchers, config)
--     local root = config.root_dir or vim.fn.getcwd()
--     local venv = root .. '/.venv/bin/typed-jinja-lsp'
--     local exe = (vim.uv or vim.loop).fs_stat(venv) and venv or 'typed-jinja-lsp'
--     return vim.lsp.rpc.start({ exe }, dispatchers)
--   end
-- or the uv form: cmd = { 'uv', 'run', 'typed-jinja-lsp' }

return {
  cmd = { 'typed-jinja-lsp' },
  filetypes = { 'jinja', 'html.jinja' },
  root_markers = { 'pyproject.toml', '.git' },
}
