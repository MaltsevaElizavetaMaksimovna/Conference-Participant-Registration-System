
export const matchesSearch = (fullName: string, query: string): boolean => {
    const normalizedName = fullName.toLowerCase().replace(/ё/g, 'е');
    const normalizedQuery = query.toLowerCase().replace(/ё/g, 'е').trim();

    if (!normalizedQuery) return true;

    const words = normalizedQuery.split(/\s+/).filter(Boolean);

    return words.every(word => normalizedName.includes(word));
};