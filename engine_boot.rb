# frozen_string_literal: true
require 'json'
require 'digest'
require 'fileutils'
ENGINE_ROOT = File.expand_path('../18xx-master', __dir__)
require File.join(ENGINE_ROOT, 'lib/engine')
# Only load the Ruby path walker. The final %x block defines the browser's
# JavaScript optimizer; executing it in native Ruby would invoke cmd.exe.
router_file = File.join(ENGINE_ROOT, 'lib/engine/auto_router.rb')
router_source = File.read(router_file, encoding: 'UTF-8')
marker = "\n    %x{"
raise 'Upstream router layout changed; inspect native adapter' unless router_source.include?(marker)
eval(router_source.split(marker, 2).first + "\n  end\nend\n", TOPLEVEL_BINDING, router_file, 1)
LOGGER.level = ::Logger::FATAL
