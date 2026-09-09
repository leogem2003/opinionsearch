1. User adds their opinion in web UI with attrib:
   1. optional general location/country
   2. Topic with (+AI suggested) 
   3. Cookie/user identifier
   4. timestamp
   5. score/urgency
2. Backend creates embeddings foreach oppinion, inserts into vector database
3. Page displays Oppinions in 2-D projected space with clustering
   1. Filters based on attributes
   2. Inspect opionions/clusters in more detail
   3. Discover/group opposite opinions
   4. Add comments/collaborate/discuss foreach oppinion/clustering
   