#!/bin/sh
# Run the unit tests. With only the Command Line Tools installed (no Xcode), SwiftPM
# doesn't find the Swift Testing framework on its own, so point it there.
F=/Library/Developer/CommandLineTools/Library/Developer/Frameworks
L=/Library/Developer/CommandLineTools/Library/Developer/usr/lib
exec swift test -Xswiftc -F -Xswiftc "$F" -Xlinker -F -Xlinker "$F" \
    -Xlinker -rpath -Xlinker "$F" -Xlinker -rpath -Xlinker "$L" "$@"
