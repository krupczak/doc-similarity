"""
Semantic document similarity using Gensim

@author: 4oh4
28/03/2020

This class is based on the Gensim Soft Cosine Tutorial notebook:
https://github.com/RaRe-Technologies/gensim/blob/develop/docs/notebooks/soft_cosine_tutorial.ipynb

"""

import logging
from re import sub
import threading
from multiprocessing import cpu_count

import numpy as np

import gensim.downloader as api
from gensim.utils import simple_preprocess
from gensim.corpora import Dictionary
from gensim.models import TfidfModel
from gensim.models import WordEmbeddingSimilarityIndex
from gensim.similarities import SparseTermSimilarityMatrix
from gensim.similarities import SoftCosineSimilarity
from gensim.models.keyedvectors import Word2VecKeyedVectors

# Import and download the most up-to-date stopwords from NLTK
# from nltk import download
# from nltk.corpus import stopwords
# download('stopwords')  # Download stopwords list.
# nltk_stop_words = set(stopwords.words("english"))

# Or use a hard-coded list of English stopwords
nltk_stop_words = {'a','about','above','after','again','against','ain','all','am','an','and','any','are','aren',"aren't",'as','at','be','because','been','before','being','below','between','both','but','by','can','couldn',"couldn't",'d','did','didn',"didn't",'do','does','doesn',"doesn't",'doing','don',"don't",'down','during','each','few','for','from','further','had','hadn',"hadn't",'has','hasn',"hasn't",'have','haven',"haven't",'having','he','her','here','hers','herself','him','himself','his','how','i','if','in','into','is','isn',"isn't",'it',"it's",'its','itself','just','ll','m','ma','me','mightn',"mightn't",'more','most','mustn',"mustn't",'my','myself','needn',"needn't",'no','nor','not','now','o','of','off','on','once','only','or','other','our','ours','ourselves','out','over','own','re','s','same','shan',"shan't",'she',"she's",'should',"should've",'shouldn',"shouldn't",'so','some','such','t','than','that',"that'll",'the','their','theirs','them','themselves','then','there','these','they','this','those','through','to','too','under','until','up','ve','very','was','wasn',"wasn't",'we','were','weren',"weren't",'what','when','where','which','while','who','whom','why','will','with','won',"won't",'wouldn',"wouldn't",'y','you',"you'd","you'll","you're","you've",'your','yours','yourself','yourselves'}


class DocSim:
    """
    Find documents that are similar to a query string.
    Calculated using word similarity (Soft Cosine Similarity) of word embedding vectors

    Example usage:

    # Use default model (glove-wiki-gigaword-50)
    docsim = DocSim()
    docsim.similarity_query(query_string, documents)

    # Or, specify a preferred, pre-existing Gensim model with custom stopwords and verbose mode    
    docsim = DocSim(model='glove-twitter-25', stopwords=['the', 'and', 'are'], verbose=True)
    docsim.similarity_query(query_string, documents)

    # Or, supply a custom pre-initialised model in gensim.models.keyedvectors.Word2VecKeyedVectors format
    docsim = DocSim(model=myModel)
    docsim.similarity_query(query_string, documents)    
    """

    default_model = "glove-wiki-gigaword-50"
    model_ready = False  # Only really relevant to threaded sub-class
    
    def __init__(self, model=None, stopwords=None, verbose=False):
        # Constructor

        self.verbose = verbose

        self.setup_model(model)

        if stopwords is None:
            self.stopwords = nltk_stop_words
        else:
            self.stopwords = stopwords


    def setup_model(self, model):
        # Determine which model to use, download/load it, and create the similarity_index
        
        if isinstance(model, Word2VecKeyedVectors):
            # Use supplied model
            self.model = model
        elif isinstance(model, str):
            # Try to download named model
            if self.verbose: 
                print(f'Loading word vector model: {model}')
            self.model = api.load(model)
            if self.verbose: 
                print('Model loaded')
        elif model is None:
            # Download/use default GloVe model
            if self.verbose: 
                print(f'Loading default GloVe word vector model: {self.default_model}')
            self.model = api.load(self.default_model)
            if self.verbose: 
                print('Model loaded')
        else:
            raise ValueError('Unable to load word vector model')

        self.similarity_index = WordEmbeddingSimilarityIndex(self.model)
        
        self.model_ready = True


    def preprocess(self, doc: str):
        # Clean up input document string, remove stopwords, and tokenize
        doc = sub(r'<img[^<>]+(>|$)', " image_token ", doc)
        doc = sub(r'<[^<>]+(>|$)', " ", doc)
        doc = sub(r'\[img_assist[^]]*?\]', " ", doc)
        doc = sub(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', " url_token ", doc)
        
        return [token for token in simple_preprocess(doc, min_len=0, max_len=float("inf")) if token not in self.stopwords]


    def _softcossim(self, query: str, documents: list):
        # Compute Soft Cosine Measure between the query and each of the documents.
        query = self.tfidf[self.dictionary.doc2bow(query)]
        index = SoftCosineSimilarity(
            self.tfidf[[self.dictionary.doc2bow(document) for document in documents]],
            self.similarity_matrix)
        similarities = index[query]

        return similarities


    def _find_similar_terms(self, query, corpus, term_limit=5):
        """
        For each term in the search query, find the most similar words in each document

        Arguments:
            query: (list) pre-processed/tokenised list of query words
            corpus: (list) of list of pre-processed/tokenised words from documents
        Returns:
            doc_similar_terms: (list) of list of similar terms for each document
        """

        doc_similar_terms = []
        for term in query:
            idx1 = self.dictionary.token2id[term]
            for document in corpus:
                results_this_doc = []
                for word in set(document):  # iterate through the words in the document and calc. score
                    idx2 = self.dictionary.token2id[word]
                    score = self.similarity_matrix.matrix[idx1, idx2]
                    if score > 0.0:
                        results_this_doc.append((word, score))
                results_this_doc = sorted(results_this_doc, reverse=True, key=lambda x: x[1])  # sort results by score
                results_this_doc = results_this_doc[:min(len(results_this_doc), term_limit)]  # take the top results
                doc_similar_terms.append(results_this_doc)
        
        return doc_similar_terms


    def similarity_query(self, query_string: str, documents: list, explain=False):
        """
        Run a new similarity ranking, for query_string against each of the documents

        Arguments:
            query_string: (string)
            documents: (list) of string documents to compare query_string against
            explain: (bbol) if True, highest scoring words are also returned

        Returns:
            list: (index, score, similar_terms) tuples for each of the documents
            or            
            list: (index, score) tuples for each of the documents
            or
            None: if model is not ready/available
        """

        if self.model_ready:
        
            corpus = [self.preprocess(document) for document in documents]
            query = self.preprocess(query_string)
            
            if self.verbose:
                print(f'{len(corpus)} documents loaded into corpus')
            
            self.dictionary = Dictionary(corpus+[query])
            self.tfidf = TfidfModel(dictionary=self.dictionary)
            self.similarity_matrix = SparseTermSimilarityMatrix(self.similarity_index, 
                                                self.dictionary, self.tfidf, nonzero_limit=100)
                        
            scores = self._softcossim(query, corpus)

            sorted_indexes = np.argsort(scores)[::-1]
            sorted_scores = scores[sorted_indexes]

            if explain:

                similar_terms = self._find_similar_terms(query, corpus)
                results = [(idx, score, terms) for idx, score, terms in zip(sorted_indexes, sorted_scores, similar_terms)]

            else:

                results = [(idx, score) for idx, score in zip(sorted_indexes, sorted_scores)]

            return results

        else:
            if self.verbose: 
                print('DocSim model not ready - cannot evaluate')

            return None


class DocSim_threaded(DocSim):
    """
    Threaded verion to load model (long running process) in background. Everything else same as standard version.

    Find documents that are similar to a query string.
    Calculated using word similarity (Soft Cosine Similarity) of word embedding vectors

    Example usage:

    docsim = DocSim()
    docsim.similarity_query(query_string, documents)
    """
    
    def __init__(self, model=None, stopwords=None, verbose=False):
        # Constructor

        self.verbose = verbose

        self._threaded_load(model)
            
        if stopwords is None:
            self.stopwords = nltk_stop_words
    

    def _threaded_load(self, model):
        """
        # Setup the model in a separate thread
        """

        self.thread = threading.Thread(target=self.setup_model, args=[model])
        self.thread.setDaemon(True)
        self.thread.start()
