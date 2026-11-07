"""Session label matching and word alignment; real model evidence lives in reports."""
import numpy as np
from service.diarization import assign_clusters,label_words,ConversationDiarizer
from types import SimpleNamespace

def test_local_cluster_numbers_can_swap_without_changing_session_speaker_ids():
    registry=[{'centroid':np.array([1.,0.])},{'centroid':np.array([0.,1.])}]
    old=[{'start':0,'end':4,'speaker':0},{'start':4,'end':8,'speaker':1}]
    turns=[{'start':0,'end':4,'speaker':7},{'start':4,'end':8,'speaker':3}]
    mapping=assign_clusters({7:np.array([1.,0.]),3:np.array([0.,1.])},turns,registry,old)
    assert mapping=={7:0,3:1} and len(registry)==2

def test_overlap_anchors_prevent_a_voice_label_flip_with_noisy_new_embeddings():
    registry=[{'centroid':np.array([1.,0.])},{'centroid':np.array([0.,1.])}]
    old=[{'start':10,'end':14,'speaker':0},{'start':14,'end':18,'speaker':1}]
    turns=[{'start':10,'end':14,'speaker':1},{'start':14,'end':18,'speaker':0}]
    mapping=assign_clusters({1:np.array([.6,.8]),0:np.array([.8,.6])},turns,registry,old)
    assert mapping=={1:0,0:1} and len(registry)==2

def test_new_person_does_not_take_an_existing_identity_without_match_or_overlap():
    registry=[{'centroid':np.array([1.,0.,0.])}]
    mapping=assign_clusters({4:np.array([0.,1.,0.])},[{'start':30,'end':35,'speaker':4}],registry,[])
    assert mapping[4]==1 and len(registry)==2

def test_words_follow_neural_speaker_turns_without_splitting_word_objects():
    words=[{'start':0,'end':.8,'text':'one'},{'start':1.1,'end':1.8,'text':'two'}]
    turns=[{'start':0,'end':1,'speaker':4},{'start':1,'end':2,'speaker':2}]
    groups=label_words(words,turns)
    assert groups==[(4,[words[0]]),(2,[words[1]])]

def test_fixed_two_person_bank_accepts_local_voice_fragments_without_new_people():
    registry=[{'centroid':np.array([1.,0.])},{'centroid':np.array([0.,1.])}]
    turns=[{'start':0,'end':2,'speaker':4},{'start':2,'end':4,'speaker':5},{'start':4,'end':6,'speaker':6}]
    previous=[{'start':0,'end':4,'speaker':0},{'start':4,'end':6,'speaker':1}]
    mapping=assign_clusters({4:np.array([1.,0.]),5:np.array([.9,.1]),6:np.array([0.,1.])},turns,registry,previous,2)
    assert mapping=={4:0,5:0,6:1} and len(registry)==2

def test_activity_without_recognized_words_cannot_create_a_voice_reference():
    diarizer=ConversationDiarizer.__new__(ConversationDiarizer)
    diarizer.model=SimpleNamespace(process=lambda audio:SimpleNamespace(sort_by_start_time=lambda:[SimpleNamespace(start=0,end=3,speaker=0)]))
    diarizer.encode=lambda audio:(_ for _ in ()).throw(AssertionError('Non-lexical activity must not be enrolled'))
    registry=[]
    turns,_=diarizer.diarize(np.ones(48000,dtype=np.float32),0,registry,[],8,[])
    assert turns==[] and registry==[]


def test_same_person_local_fragments_do_not_fill_the_bank_with_duplicate_ids():
    registry=[]
    vectors={0:np.array([1.,0.,0.]),1:np.array([.8,.6,0.]),2:np.array([0.,0.,1.])}
    turns=[{'start':i*3,'end':i*3+3,'speaker':i} for i in vectors]
    mapping=assign_clusters(vectors,turns,registry,[],2)
    assert mapping=={0:0,1:0,2:1} and len(registry)==2


def test_wrong_overlap_and_contaminated_profiles_cannot_overrule_a_clear_reference():
    registry=[{'centroid':np.array([1.,0.]),'profiles':[np.array([0.,1.])]},
              {'centroid':np.array([0.,1.]),'profiles':[]}]
    # A prior classification was wrong for this exact time range.
    turns=[{'start':0,'end':8,'speaker':7}]
    old=[{'start':0,'end':8,'speaker':0}]
    mapping=assign_clusters({7:np.array([0.,1.])},turns,registry,old,2)
    assert mapping=={7:1}
    assert len(registry[0]['profiles'])==1
