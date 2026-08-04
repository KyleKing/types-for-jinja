-- Republish a generated stub's diagnostics onto the template that produced it.
--
-- Mirroring has to live in the editor. types-for-jinja writes a Python stub and the
-- project's own Python language server type-checks it, but one server cannot read
-- another server's diagnostics, so nothing on the Python side can move them.
--
-- The flow, per template buffer:
--   1. ask the types-for-jinja server which stub this template generates
--   2. load that stub as a hidden buffer, so the Python server attaches and checks it
--   3. on DiagnosticChanged for the stub, ask the server where those positions belong in
--      the template, and set them on the template buffer under our own namespace
--
-- Positions come back from the server rather than being computed here, so the mirror and
-- `types-for-jinja remap` can never disagree about a column.

local M = {}

local NS = vim.api.nvim_create_namespace('types_for_jinja_mirror')
local SERVER = 'types_for_jinja'

---@type table<integer, integer> stub buffer -> template buffer
local template_of = {}
---@type table<integer, integer> template buffer -> stub buffer
local stub_of = {}

local function client(bufnr)
  return vim.lsp.get_clients({ bufnr = bufnr, name = SERVER })[1]
end

--- Ask the types-for-jinja server a question about `bufnr`'s template.
local function ask(bufnr, method, params, on_result)
  local found = client(bufnr)
  if not found then return end
  found:request(method, params, function(err, result)
    if not err and result then on_result(result) end
  end, bufnr)
end

--- Load the stub without showing it, so the Python language server attaches and checks it.
local function load_hidden(path)
  local bufnr = vim.fn.bufadd(path)
  if not vim.api.nvim_buf_is_loaded(bufnr) then
    vim.fn.bufload(bufnr)
  end
  vim.bo[bufnr].buflisted = false
  return bufnr
end

--- Copy `stub_buf`'s diagnostics onto its template, translated through the server.
---
--- Only errors and warnings cross over. A hint or an informational note in a stub is about
--- the generated scaffolding rather than the template ("_tj_default is not accessed"), and
--- there is nothing a template author could do about it.
local function mirror(stub_buf)
  local template_buf = template_of[stub_buf]
  if not template_buf or not vim.api.nvim_buf_is_valid(template_buf) then return end

  local found = vim.diagnostic.get(stub_buf, {
    severity = { min = vim.diagnostic.severity.WARN },
  })
  if #found == 0 then
    vim.diagnostic.set(NS, template_buf, {})
    return
  end

  local positions = {}
  for _, entry in ipairs(found) do
    positions[#positions + 1] = { line = entry.lnum, character = entry.col }
  end

  ask(template_buf, 'types-for-jinja/remap', {
    stub = vim.api.nvim_buf_get_name(stub_buf),
    positions = positions,
  }, function(result)
    local mapped = {}
    for index, entry in ipairs(found) do
      local at = result.positions and result.positions[index]
      if at then
        mapped[#mapped + 1] = {
          lnum = at.line,
          col = at.character,
          end_lnum = at.line,
          end_col = at.character + 1,
          severity = entry.severity,
          message = entry.message,
          source = entry.source,
          code = entry.code,
        }
      end
    end
    vim.diagnostic.set(NS, template_buf, mapped)
  end)
end

--- Start mirroring for a template buffer, once the types-for-jinja server has written its stub.
function M.attach(template_buf)
  if stub_of[template_buf] then return end
  ask(template_buf, 'types-for-jinja/stubFor', {
    template = vim.api.nvim_buf_get_name(template_buf),
  }, function(result)
    if not result.stub then return end
    local stub_buf = load_hidden(result.stub)
    stub_of[template_buf] = stub_buf
    template_of[stub_buf] = template_buf
    mirror(stub_buf)
  end)
end

--- Forget a template buffer and clear what it mirrored.
function M.detach(template_buf)
  local stub_buf = stub_of[template_buf]
  stub_of[template_buf] = nil
  if stub_buf then template_of[stub_buf] = nil end
end

--- Wire the autocmds. Safe to call more than once.
---@param opts? { filetypes?: string[] }
function M.setup(opts)
  opts = opts or {}
  local group = vim.api.nvim_create_augroup('types_for_jinja_mirror', { clear = true })

  vim.api.nvim_create_autocmd('LspAttach', {
    group = group,
    callback = function(args)
      local attached = vim.lsp.get_client_by_id(args.data.client_id)
      if attached and attached.name == SERVER then
        M.attach(args.buf)
      end
    end,
  })

  -- The stub is only checked after the server writes it, which happens on open, on save,
  -- and once an edit settles. Re-asking on save covers a template whose stub did not exist
  -- the first time round.
  vim.api.nvim_create_autocmd('BufWritePost', {
    group = group,
    pattern = opts.filetypes and nil or '*',
    callback = function(args)
      if stub_of[args.buf] then
        mirror(stub_of[args.buf])
      elseif client(args.buf) then
        M.attach(args.buf)
      end
    end,
  })

  vim.api.nvim_create_autocmd('DiagnosticChanged', {
    group = group,
    callback = function(args)
      if template_of[args.buf] then
        mirror(args.buf)
      end
    end,
  })

  vim.api.nvim_create_autocmd('BufDelete', {
    group = group,
    callback = function(args) M.detach(args.buf) end,
  })
end

return M
