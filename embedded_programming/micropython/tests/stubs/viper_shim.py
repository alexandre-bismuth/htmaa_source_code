# Lets viper-annotated code run as plain Python on the host (the unix port has no native emitter on arm64).
def ptr8(x):
    return x


ptr16 = ptr32 = ptr8


def uint(x):
    return x & 0xFFFFFFFF
