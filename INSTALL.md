# Preparing the source tree

If you just cloned the git repository, make sure you also
cloned the submodules, which you can do using:

    $ git submodule update --init

# Building

## Build dependencies

The required build dependencies are: (devel packages of these)

 - PyQt5
 - Qt5 dev tools
 - qtchooser

On Debian and Ubuntu, use these commands as root to install all build
dependencies:

    apt-get install \
      python3-pyqt5 pyqt5-dev-tools \
      qtchooser qttools5-dev-tools


To build RaySession, simply run as usual:

    make

Depending of the distribution you might need to use the LRELEASE variable
to build.  If you don't have 'lrelease' executable but 'lrelease-qt5' use:

    make LRELEASE=lrelease-qt5

# Installing

To install RaySession, simply run as usual:

    make install

Packagers can make use of the 'PREFIX' and 'DESTDIR' variable during install,
like this:

    make install PREFIX=/usr DESTDIR=./test-dir

# Uninstalling

To uninstall RaySession, run:

    make uninstall

# Running

You can run RaySession without install, by using:

    ./src/bin/raysession

To run it, you'll additionally need:

   - python3-liblo

IMPORTANT: since python 3.11, because pyliblo has been totally abandonned
by Dominic Sacre, you need to use the following fork:

    https://github.com/gesellkammer/pyliblo3

Simply install it with:

    python3 -m pip install pyliblo3
