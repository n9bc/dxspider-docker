#!/usr/bin/env sh
# Literal token -> value substitution for entrypoint config rendering.
# Single source of truth, sourced by entrypoint.sh and unit-tested.
#
# render_template SRC DST TOKEN VALUE [TOKEN VALUE ...]
#
# Values are passed to perl as @ARGV DATA and inserted via a variable, so
# NO sed/regex/shell metacharacter in a value is ever interpreted: | & \ /
# $ @ and newlines are all inert. \Q...\E literal-quotes the token. Tokens
# are applied in argument order (same sequential semantics as the previous
# `sed -e ... -e ...` pipeline). The whole file is slurped and reprinted, so
# the template's exact trailing newline is preserved (byte-identical to sed
# for normal values). A missing template is a hard error (perl die ->
# non-zero), matching the previous required-template behaviour.
render_template() {
    _rt_src="$1"
    _rt_dst="$2"
    shift 2
    perl -e '
        my $src = shift @ARGV;
        open my $fh, "<", $src or die "render_template: cannot open $src: $!\n";
        local $/;
        my $t = <$fh>;
        close $fh;
        while (@ARGV) {
            my $tok = shift @ARGV;
            my $val = shift @ARGV;
            $t =~ s/\Q$tok\E/$val/g;
        }
        print $t;
    ' "$_rt_src" "$@" > "$_rt_dst"
}
