import re
from itertools import chain

class Matcher(object):
    """
    Applies a function f : c -> {0,1} to a generator of candidates,
    returning only candidates _c_ s.t. _f(c) == 1_,
    where f can be compositionally defined.
    """
    def __init__(self, *children, **opts):
        self.children           = children
        self.opts               = opts
        self.longest_match_only = self.opts.get('longest_match_only', False)
        self.init()
    
    def init(self):
        pass

    def _f(self, c):
        """The internal (non-composed) version of filter function f"""
        return 1

    def f(self, c):
        """
        The recursicvely composed version of filter function f
        By default, returns logical **conjunction** of opeerator and single child operator
        """
        if len(self.children) == 0:
            return self._f(c)
        elif len(self.children) == 1:
            return self._f(c) * self.children[0].f(c)
        else:
            raise Exception("%s does not support more than one child Matcher" % self.__name__)

    def _is_subspan(self, c, span):
        """Tests if candidate c is subspan of span, where span is defined specific to candidate type"""
        return False

    def _get_span(self, c):
        """Gets a tuple that identifies a span for the specific candidate class that c belongs to"""
        return c

    def apply(self, candidates):
        """
        Apply the Matcher to a **generator** of candidates
        Optionally only takes the longest match (NOTE: assumes this is the *first* match)
        """
        seen_spans = set()
        for c in candidates:
            if self.f(c) > 0 and (not self.longest_match_only or not any([self._is_subspan(c, s) for s in seen_spans])):
                if self.longest_match_only:
                    seen_spans.add(self._get_span(c))
                yield c


WORDS = 'words'

class NgramMatcher(Matcher):
    """Matcher base class for Ngram objects"""
    def _is_subspan(self, c, span):
        """Tests if candidate c is subspan of span, where span is defined specific to candidate type"""
        return c.char_start >= span[0] and c.char_end <= span[1]

    def _get_span(self, c):
        """Gets a tuple that identifies a span for the specific candidate class that c belongs to"""
        return (c.char_start, c.char_end)


class DictionaryMatch(NgramMatcher):
    """Selects candidate Ngrams that match against a given list d"""
    def init(self):
        self.d           = frozenset(self.opts['d'])
        self.ignore_case = self.opts.get('ignore_case', True) 
        self.attrib      = self.opts.get('attrib', WORDS)
    
    def _f(self, c):
        p = c.get_attrib_span(self.attrib)
        p = p.lower() if self.ignore_case else p
        return 1 if p in self.d else 0


class Union(NgramMatcher):
    """Takes the union of candidate sets returned by child operators"""
    def f(self, c):
       for child in self.children:
           if child.f(c) > 0:
               return 1
       return 0


class Concat(NgramMatcher):
    """
    Selects candidates which are the concatenation of adjacent matches from child operators
    NOTE: Currently slices on **word index** and considers concatenation along these divisions only
    """
    def init(self):
        self.permutations   = self.opts.get('permutations', False)
        self.left_required  = self.opts.get('left_required', True)
        self.right_required = self.opts.get('right_required', True)
        self.ignore_sep     = self.opts.get('ignore_sep', True)
        self.sep            = self.opts.get('sep', " ")

    def f(self, c):
        if len(self.children) != 2:
            raise ValueError("Concat takes two child Matcher objects as arguments.")
        if not self.left_required and self.children[1].f(c):
            return 1
        if not self.right_required and self.children[0].f(c):
            return 1

        # Iterate over candidate splits **at the word boundaries**
        for wsplit in range(c.word_start+1, c.word_end+1):
            csplit = c.word_to_char_index(wsplit) - c.char_start  # NOTE the switch to **candidate-relative** char index

            # Optionally check for specific separator
            if self.ignore_sep or c.get_span()[csplit-1] == self.sep:
                c1 = c[:csplit-len(self.sep)]
                c2 = c[csplit:]
                if self.children[0].f(c1) and self.children[1].f(c2):
                    return 1
                if self.permutations and self.children[1].f(c1) and self.children[0].f(c2):
                    return 1
        return 0


class RegexMatch(NgramMatcher):
    """Base regex class- does not specify specific semantics of *what* is being matched yet"""
    def init(self):
        self.rgx         = self.opts['rgx']
        self.ignore_case = self.opts.get('ignore_case', True)
        self.attrib      = self.opts.get('attrib', WORDS)
        self.sep         = self.opts.get('sep', " ")

        # Compile regex matcher
        self.r = re.compile(self.rgx, flags=re.I if self.ignore_case else 0)

    def _f(self, c):
        raise NotImplementedError()


class RegexMatchSpan(RegexMatch):
    """Matches regex pattern on **full concatenated span**"""
    def _f(self, c):
        return 1 if self.r.match(c.get_attrib_span(self.attrib, sep=self.sep)) is not None else 0


class RegexMatchEach(RegexMatch):
    """Matches regex pattern on **each token**"""
    def _f(self, c):
        return 1 if all([self.r.match(t) is not None for t in c.get_attrib_tokens(self.attrib)]) else 0


class CandidateExtractor(object):
    """Temporary class for interfacing with the post-candidate-extraction code"""
    def __init__(self, candidate_space, matcher):
        self.candidate_space = candidate_space
        self.matcher         = matcher

    def apply(self, s):
        for c in self.matcher.apply(self.candidate_space.apply(s)):
            try:
                yield range(c.word_start, c.word_end+1), 'MATCHER'
            except:
                raise Exception("Candidate must have word_start and word_end attributes.")