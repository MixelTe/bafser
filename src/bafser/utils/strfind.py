def strfind(s: str, words: list[str]) -> int:
    indices = [s.find(word) for word in words]
    valid_indices = (i for i in indices if i != -1)
    return min(valid_indices, default=-1)
