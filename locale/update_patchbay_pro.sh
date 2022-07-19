#!/bin/bash

# This is a little script for refresh raysession.pro and update .ts files.
# TRANSLATOR: if you want to translate the program, you don't need to run it !

contents=""

this_script=`realpath "$0"`
locale_root=`dirname "$this_script"`
code_root=`dirname "$locale_root"`
cd "$code_root/resources/ui/patchbay"

for file in *.ui;do
    contents+="FORMS += ../resources/ui/patchbay/$file
"
done


for dir in patchbay patchbay/patchcanvas;do
    cd "$code_root/src/gui/$dir"
    
    for file in *.py;do
        [[ "$file" =~ ^ui_ ]] && continue
        
        if cat "$file"|grep -q _translate;then
            contents+="SOURCES += ../src/gui/$dir/${file}
"
        fi
    done
done

contents+="
TRANSLATIONS += patchbay_en.ts
TRANSLATIONS += patchbay_fr.ts
"

echo "$contents" > "$locale_root/patchbay.pro"

pylupdate5 "$locale_root/patchbay.pro"