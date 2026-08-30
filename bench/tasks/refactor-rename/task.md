`mk_k` and `mk_k_prefix` are badly named. Rename them to `record_key` and
`kind_prefix` everywhere they appear.

The suite must still pass, and the old names must not be left anywhere in the
project — not in an import, not in an alias kept for compatibility, not in a
comment.
