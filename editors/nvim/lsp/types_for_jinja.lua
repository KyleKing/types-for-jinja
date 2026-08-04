-- types-for-jinja language server: static type checking for Jinja templates.
--
-- Install: copy this file to ~/.config/nvim/lsp/types_for_jinja.lua, then in your config:
--   vim.lsp.enable('types_for_jinja')
--
-- Filetype detection for templates (add once to your config):
--   vim.filetype.add({
--     extension = { jinja = 'jinja' },
--     pattern = { ['.*%.html%.jinja'] = 'jinja' },
--   })
--
-- The default cmd assumes `types-for-jinja-lsp` is on PATH (an active venv, or `uv sync`).
-- For a project-local venv without activation, swap cmd for a resolver like:
--   cmd = function(dispatchers, config)
--     local root = config.root_dir or vim.fn.getcwd()
--     local venv = root .. '/.venv/bin/types-for-jinja-lsp'
--     local exe = (vim.uv or vim.loop).fs_stat(venv) and venv or 'types-for-jinja-lsp'
--     return vim.lsp.rpc.start({ exe }, dispatchers)
--   end
-- or the uv form: cmd = { 'uv', 'run', 'types-for-jinja-lsp' }

return {
  cmd = { 'types-for-jinja-lsp' },
  filetypes = { 'jinja', 'html.jinja' },
  root_markers = { 'pyproject.toml', '.git' },
}
