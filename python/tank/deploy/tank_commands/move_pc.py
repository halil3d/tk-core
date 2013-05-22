"""
Copyright (c) 2012 Shotgun Software, Inc
----------------------------------------------------

Methods for handling of the tank command

"""

from ... import pipelineconfig

from ...util import shotgun
from ...platform import constants
from ...errors import TankError

from .action_base import Action

import sys
import os
import shutil


class MovePCAction(Action):
    
    def __init__(self):
        Action.__init__(self, 
                        "move_configuration", 
                        Action.PC_LOCAL, 
                        ("Moves this configuration from its current disk location to a new location."), 
                        "Admin")
    
    def _cleanup_old_location(self, log, path):
        
        found_storage_lookup_file = False
        for root, dirs, files in os.walk(path, topdown=False):
            for name in files:
                if name == "tank_configs.yml":
                    found_storage_lookup_file = True
                    
                else:
                    full_path = os.path.join(root, name)
                    log.debug("Removing %s..." % full_path)
                    try:
                        os.remove(full_path)
                    except Exception, e:
                        log.warning("Could not delete file %s. Error Reported: %s" % (full_path, e))
                        
            for name in dirs:
                full_path = os.path.join(root, name)
                if found_storage_lookup_file and full_path == os.path.join(path, "config"):
                    log.debug("Not deleting folder %s since we have a storage lookup file" % full_path)
                    
                else:
                    log.debug("Deleting folder %s..." % full_path)
                    try:
                        os.rmdir(full_path)
                    except Exception, e:
                        log.warning("Could not remove folder %s. Error Reported: %s" % (full_path, e))
                            
    
    def _copy_folder(self, level, log, src, dst): 
        """
        Alternative implementation to shutil.copytree
        Copies recursively with very open permissions.
        Creates folders if they don't already exist.
        """
        if not os.path.exists(dst):
            log.debug("mkdir 0777 %s" % dst)
            os.mkdir(dst, 0777)
    
        names = os.listdir(src) 
        for name in names:
    
            srcname = os.path.join(src, name) 
            dstname = os.path.join(dst, name) 
                    
            if os.path.isdir(srcname): 
                if level < 3:
                    log.info("Copying %s..." % srcname)
                self._copy_folder(log, level+1, srcname, dstname)             
            else: 
                if dstname.endswith("tank_configs.yml") and os.path.dirname(dstname).endswith("config"):
                    log.debug("NOT COPYING CONFIG FILE %s -> %s" % (srcname, dstname))
                else:
                    shutil.copy(srcname, dstname)
                    log.debug("Copy %s -> %s" % (srcname, dstname))
                    # if the file extension is sh, set executable permissions
                    if dstname.endswith(".sh") or dstname.endswith(".bat"):
                        # make it readable and executable for everybody
                        os.chmod(dstname, 0777)
                        log.debug("CHMOD 777 %s" % dstname)
        
    
    
    def run(self, log, args):
        
        if len(args) != 3:
            log.info("Syntax: move_configuration linux_path windows_path mac_path")
            log.info("")
            log.info("You typically need to quote your paths, like this:")
            log.info("")
            log.info('> tank move_configuration "/linux_root/my_config" "p:\\configs\\my_config" "/mac_root/my_config"')
            log.info("")
            log.info("If you want to leave a platform blank, just just empty quotes. For example, "
                     "if you want a configuration which only works on windows, do like this: ")
            log.info("")
            log.info('> tank move_configuration "" "p:\\configs\\my_config" ""')
            raise TankError("Wrong number of parameters!")
        
        linux_path = args[0]
        windows_path = args[1]
        mac_path = args[2]
        new_paths = {"mac_path": mac_path, 
                     "windows_path": windows_path, 
                     "linux_path": linux_path}
        
        sg = shotgun.create_sg_connection()
        pipeline_config_id = self.tk.pipeline_configuration.get_shotgun_id()
        data = sg.find_one(constants.PIPELINE_CONFIGURATION_ENTITY, 
                           [["id", "is", pipeline_config_id]],
                           ["code", "mac_path", "windows_path", "linux_path"])
        
        if data is None:
            raise TankError("Could not find this Pipeline Configuration in Shotgun!")
        
        log.info("Overview of Configuration '%s'" % data.get("code"))
        log.info("--------------------------------------------------------------")
        log.info("")
        log.info("Current Linux Path:   %s" % data.get("linux_path"))
        log.info("Current Windows Path: %s" % data.get("windows_path"))
        log.info("Current Mac Path:     %s" % data.get("mac_path"))
        log.info("")
        log.info("New Linux Path:   %s" % linux_path)
        log.info("New Windows Path: %s" % windows_path)
        log.info("New Mac Path:     %s" % mac_path)
        log.info("")
        
        val = raw_input("Are you sure you want to move your configuration? [Yes/No] ")
        if not val.lower().startswith("y"):
            raise TankError("Aborted by User.")

        # ok let's do it!
        storage_map = {"linux2": "linux_path", "win32": "windows_path", "darwin": "mac_path" }
        local_source_path = data.get(storage_map[sys.platform])
        local_target_path = new_paths.get(storage_map[sys.platform])
        source_sg_code_location = os.path.join(local_source_path, "config", "core", "install_location.yml")
        
        if not os.path.exists(local_source_path):
            raise TankError("The path %s does not exist on disk!" % local_source_path)
        if os.path.exists(local_target_path):
            raise TankError("The path %s already exists on disk!" % local_target_path)
        if not os.path.exists(source_sg_code_location):
            raise TankError("The required config file %s does not exist on disk!" % source_sg_code_location)

        # also - we currently don't support moving PCs which have a localized API
        # (because these may be referred to by other PCs that are using their API
        # TODO: later on, support moving these. For now, just error out.
        api_file = os.path.join(local_source_path, "install", "core", "_core_upgrader.py")
        if not os.path.exists(api_file):
            raise TankError("Looks like the Configuration you are trying to move has a localized "
                            "API. This is not currently supported.")
        
        # sanity check target folder
        parent_target = os.path.dirname(local_target_path)
        if not os.path.exists(parent_target):
            raise TankError("The path '%s' does not exist!" % parent_target)
        if not os.access(parent_target, os.W_OK|os.R_OK|os.X_OK):
            raise TankError("The permissions setting for '%s' is too strict. The current user "
                            "cannot create folders in this location." % parent_target)

        # first copy the data across
        old_umask = os.umask(0)
        try:

            log.info("Copying '%s' -> '%s'" % (local_source_path, local_target_path))            
            self._copy_folder(log, 0, local_source_path, local_target_path)
            
            sg_code_location = os.path.join(local_target_path, "config", "core", "install_location.yml")
            log.info("Updating cached locations in %s..." % sg_code_location)
            os.chmod(sg_code_location, 0666)
            fh = open(sg_code_location, "wt")
            fh.write("# Tank configuration file\n")
            fh.write("# This file reflects the paths in the pipeline configuration\n")
            fh.write("# entity which is associated with this location\n")
            fh.write("\n")
            fh.write("Windows: '%s'\n" % windows_path)
            fh.write("Darwin: '%s'\n" % mac_path)    
            fh.write("Linux: '%s'\n" % linux_path)                    
            fh.write("\n")
            fh.write("# End of file.\n")
            fh.close()    
            os.chmod(sg_code_location, 0444)        

            for r in self.tk.pipeline_configuration.get_data_roots().values():
                log.info("Updating storage root reference in %s.." % r)
                scm = pipelineconfig.StorageConfigurationMapping(r)
                scm.add_pipeline_configuration(mac_path, windows_path, linux_path)

        except Exception, e:
            raise TankError("Could not copy configuration! This may be because of system "
                            "permissions or system setup. This configuration will "
                            "still be functional, however data may have been partially copied "
                            "to '%s' so we recommend that that location is cleaned up. " 
                            "Error Details: %s" % (local_target_path, e))
        finally:
            os.umask(old_umask)
        
        log.info("Updating Shotgun Configuration Record...")
        sg.update(constants.PIPELINE_CONFIGURATION_ENTITY, pipeline_config_id, new_paths)
        
        # finally clean up the previous location
        log.info("Deleting original configuration files...")
        self._cleanup_old_location(log, local_source_path)
        log.info("")
        log.info("All done! Your configuration has been successfully moved.")
        
        
        
        

