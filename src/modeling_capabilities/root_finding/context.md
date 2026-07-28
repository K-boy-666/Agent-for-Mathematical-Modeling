# numerical.root_finding input context

`math-expr-v1` accepts only ASCII whitespace, `x`, ordinary finite decimal
or scientific binary64 literals (`1`, `1.`, `.5`, `1e-3`), `pi`, `e`,
arithmetic `+ - * / **`, parentheses, unary signs, and the one-argument
functions `abs sqrt exp log sin cos tan`.
All tokens are ASCII; non-ASCII whitespace, identifiers, and digits are
rejected.

Arithmetic uses conventional precedence. Power is right-associative and binds
more tightly than a leading unary sign, so `-2**2` parses as `-(2**2)`.
A sign is folded only when it syntactically targets a number token; signs
outside parentheses or sign chains remain explicit AST nodes.

Expressions are limited to 4096 UTF-8 bytes, 64 characters per numeric
literal, 256 canonical AST nodes, and canonical AST depth 32 with the root at
depth 1. Power exponents must be canonical number nodes in the inclusive
range `[-1024, 1024]`.

Canonical input materializes all defaults and persists the parsed AST, never
the raw expression text. Solver and validator evaluators share the immutable
syntax and budget contract types, but retain separate traversal, numerical
dispatch, and arithmetic error paths.
