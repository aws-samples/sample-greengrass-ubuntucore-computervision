gary@GE-WS:~/Git/sample-greengrass-ubuntucore-computervision/cv-inference$ snapcraft
Running snapcraft without a command will not be possible in future releases. Use 'snapcraft pack' instead.
Generated snap metadata
Generated component metadata
Lint warnings:
- metadata: Metadata field 'title' is missing or empty. (https://documentation.ubuntu.com/snapcraft/stable/reference/project-file/snapcraft-yaml/#title)
- metadata: Metadata field 'contact' is missing or empty. (https://documentation.ubuntu.com/snapcraft/stable/reference/project-file/snapcraft-yaml/#contact)
- metadata: Metadata field 'license' is missing or empty. (https://documentation.ubuntu.com/snapcraft/stable/reference/project-file/snapcraft-yaml/#license)
Lint information:
- metadata: Metadata field 'donation' is missing or empty. (https://documentation.ubuntu.com/snapcraft/stable/reference/project-file/snapcraft-yaml/#donation)
- metadata: Metadata field 'issues' is missing or empty. (https://documentation.ubuntu.com/snapcraft/stable/reference/project-file/snapcraft-yaml/#issues)
- metadata: Metadata field 'source-code' is missing or empty. (https://documentation.ubuntu.com/snapcraft/stable/reference/project-file/snapcraft-yaml/#source-code)
- metadata: Metadata field 'website' is missing or empty. (https://documentation.ubuntu.com/snapcraft/stable/reference/project-file/snapcraft-yaml/#website)
Cannot pack snap: error: cannot validate snap "cv-inference": layout "/var/snap/cv-inference/common/config" in an off-limits area
Detailed information: Command '['snap', 'pack', '--check-skeleton', PosixPath('/root/prime')]' returned non-zero exit status 1.
Failed to execute pack in instance.
Recommended resolution: Run the same command again with --debug to shell into the environment if you wish to introspect this failure.
Full execution log: '/home/gary/.local/state/snapcraft/log/snapcraft-20260515-172233.194495.log'
