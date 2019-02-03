# installer for SDS011 driver
# Copyright 2019 Matthew Wall
# Distributed under the terms of the GNU Public License (GPLv3)

from setup import ExtensionInstaller

def loader():
    return SDS011Installer()

class SDS011Installer(ExtensionInstaller):
    def __init__(self):
        super(SDS011Installer, self).__init__(
            version="0.1",
            name='sds011',
            description='Collect data from SDS011 particulate sensor',
            author="Matthew Wall",
            author_email="mwall@users.sourceforge.net",
            config={
                'SDS011': {
                    }
                },
            files=[('bin/user', ['bin/user/sds011.py'])]
            )
