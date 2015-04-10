import os
import sys
import token
import tokenize


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('pass directory to search in as an arg')
        sys.exit(1)

    dir = os.path.abspath(sys.argv[1])
    print('Directory: ', dir)
    print()

    c_error, c_async, c_await = 0, 0, 0

    for root, dirs, files in os.walk(dir):
        for name in files:
            if not name.endswith('.py'):
                continue

            filename = os.path.join(root, name)
            with open(filename, 'rb') as f:

                try:
                    tokens = list(tokenize.tokenize(f.readline))
                except (SyntaxError, UnicodeDecodeError) as ex:
                    print('ERROR', filename, ex)
                    c_error += 1
                    continue

                for tok in tokens:
                    if tok.type == token.NAME and \
                                    tok.string in ('await', 'async'):

                        print('{}\t{}: {}'.format(
                            tok.string, filename, tok.start))

                        if tok.string == 'await':
                            c_await += 1

                        if tok.string == 'async':
                            c_async += 1

    print()
    print('# of errors: ', c_error)
    print('# of `await`: ', c_await)
    print('# of `async`: ', c_async)
